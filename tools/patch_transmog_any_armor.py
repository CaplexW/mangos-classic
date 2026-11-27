#!/usr/bin/env python3
"""Remove every class/race/level/armor-type restriction from the transmog module.

The module (https://github.com/flekz-games/cmangos-transmog, pinned in
src/CMakeLists.txt) refuses a transmog when the item is not part of a hardcoded
per-class list of armor/weapon subclasses, when the item's AllowableClass /
AllowableRace masks do not include the character, or when Player::CanUseItem()
rejects the item (level, skill, required spell). That is why a custom warlock
cannot transmog mail, plate or shields even though the character can wear them.

This script rewrites the module source after CMake fetched it and before it is
compiled:

  * TransmogModule::IsValidTransmog() keeps only "the item has an appearance"
    (weapon or armor) and drops the class/race masks and the per-class lists.
  * GetWeaponAvailableForClass() / GetArmorAvailableForClass() are deleted and
    replaced by GetSlotsForInventoryType(), which maps an inventory type to the
    equipment slots it can be displayed in - the slot is still respected (a
    helm cannot be shown on the legs), nothing else is.
  * AddDiscoveredTransmog() uses that mapping instead of Player::ViableEquipSlots(),
    so an appearance is collectable no matter whether the character could ever
    equip the item itself.

Usage: patch_transmog_any_armor.py [<path to src/modules/transmog>]
Exit code is non-zero when the fetched module no longer contains what the patch
expects, so a broken patch never reaches the compiler silently.
"""

import os
import sys

SIG_VALID = "bool TransmogModule::IsValidTransmog(const Player* player, const ItemPrototype* itemPrototype) const"
SIG_WEAPON_HELPER = "std::vector<uint8> GetWeaponAvailableForClass(uint8 playerClass)"
SIG_ARMOR_HELPER = "std::vector<uint8> GetArmorAvailableForClass(uint8 playerClass)"
OLD_SLOT_CALL = "if (player->ViableEquipSlots(proto, &transmogItem.slots[0]))"
NEW_SLOT_CALL = "if (GetSlotsForInventoryType(proto->InventoryType, &transmogItem.slots[0]))"

NEW_HELPER = """    // Any character may transmog any weapon or armor appearance. Only the
    // inventory type decides in which equipment slots an appearance can be
    // shown; class, race, level, skill and armor type are never checked.
    bool GetSlotsForInventoryType(uint8 inventoryType, uint8* slots)
    {
        if (!slots)
            return false;

        slots[0] = NULL_SLOT;
        slots[1] = NULL_SLOT;
        slots[2] = NULL_SLOT;
        slots[3] = NULL_SLOT;

        switch (inventoryType)
        {
            case INVTYPE_HEAD:
                slots[0] = EQUIPMENT_SLOT_HEAD;
                break;
            case INVTYPE_NECK:
                slots[0] = EQUIPMENT_SLOT_NECK;
                break;
            case INVTYPE_SHOULDERS:
                slots[0] = EQUIPMENT_SLOT_SHOULDERS;
                break;
            case INVTYPE_BODY:
                slots[0] = EQUIPMENT_SLOT_BODY;
                break;
            case INVTYPE_CHEST:
            case INVTYPE_ROBE:
                slots[0] = EQUIPMENT_SLOT_CHEST;
                break;
            case INVTYPE_WAIST:
                slots[0] = EQUIPMENT_SLOT_WAIST;
                break;
            case INVTYPE_LEGS:
                slots[0] = EQUIPMENT_SLOT_LEGS;
                break;
            case INVTYPE_FEET:
                slots[0] = EQUIPMENT_SLOT_FEET;
                break;
            case INVTYPE_WRISTS:
                slots[0] = EQUIPMENT_SLOT_WRISTS;
                break;
            case INVTYPE_HANDS:
                slots[0] = EQUIPMENT_SLOT_HANDS;
                break;
            case INVTYPE_FINGER:
                slots[0] = EQUIPMENT_SLOT_FINGER1;
                slots[1] = EQUIPMENT_SLOT_FINGER2;
                break;
            case INVTYPE_TRINKET:
                slots[0] = EQUIPMENT_SLOT_TRINKET1;
                slots[1] = EQUIPMENT_SLOT_TRINKET2;
                break;
            case INVTYPE_CLOAK:
                slots[0] = EQUIPMENT_SLOT_BACK;
                break;
            case INVTYPE_WEAPON:
                slots[0] = EQUIPMENT_SLOT_MAINHAND;
                slots[1] = EQUIPMENT_SLOT_OFFHAND;
                break;
            case INVTYPE_2HWEAPON:
                slots[0] = EQUIPMENT_SLOT_MAINHAND;
                break;
            case INVTYPE_WEAPONMAINHAND:
                slots[0] = EQUIPMENT_SLOT_MAINHAND;
                break;
            case INVTYPE_SHIELD:
            case INVTYPE_HOLDABLE:
            case INVTYPE_WEAPONOFFHAND:
                slots[0] = EQUIPMENT_SLOT_OFFHAND;
                break;
            case INVTYPE_RANGED:
            case INVTYPE_THROWN:
            case INVTYPE_RANGEDRIGHT:
                slots[0] = EQUIPMENT_SLOT_RANGED;
                break;
            case INVTYPE_TABARD:
                slots[0] = EQUIPMENT_SLOT_TABARD;
                break;
            default:
                // Not an equippable appearance (bags, ammo, ...): no slot.
                return false;
        }

        return true;
    }"""

NEW_VALID = """    bool TransmogModule::IsValidTransmog(const Player* /*player*/, const ItemPrototype* itemPrototype) const
    {
        // No class, race or armor type restriction: every character may use any
        // weapon or armor appearance it owns.
        return itemPrototype && (itemPrototype->Class == ITEM_CLASS_WEAPON || itemPrototype->Class == ITEM_CLASS_ARMOR);
    }"""


def function_span(text, signature):
    """Return (start, end) of the whole function whose signature starts the block."""
    start = text.index(signature)
    # Keep the indentation of the line out of the span so the replacement supplies its own.
    while start > 0 and text[start - 1] in " \t":
        start -= 1
    index = text.index("{", start)
    depth = 0
    while index < len(text):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return start, index + 1
        index += 1
    raise RuntimeError("unbalanced braces after: " + signature)


def main():
    module_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join("src", "modules", "transmog")
    path = os.path.join(module_dir, "src", "TransmogModule.cpp")
    if not os.path.isfile(path):
        sys.exit("error: %s not found (is BUILD_MODULE_TRANSMOG enabled?)" % path)

    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        text = handle.read()

    if OLD_SLOT_CALL not in text and NEW_SLOT_CALL in text:
        print("already patched: %s" % path)
        return

    newline = "\r\n" if text.count("\r\n") * 2 > text.count("\n") else "\n"

    def block(source):
        return source.replace("\n", newline) if newline != "\n" else source

    # 1. Drop both hardcoded per-class subclass tables, install the slot mapping.
    weapon_start, _ = function_span(text, SIG_WEAPON_HELPER)
    _, armor_end = function_span(text, SIG_ARMOR_HELPER)
    text = text[:weapon_start] + block(NEW_HELPER) + text[armor_end:]

    # 2. Strip every restriction from IsValidTransmog.
    start, end = function_span(text, SIG_VALID)
    text = text[:start] + block(NEW_VALID) + text[end:]

    # 3. Collect appearances by inventory type instead of by what the character may equip.
    if OLD_SLOT_CALL not in text:
        sys.exit("error: AddDiscoveredTransmog() no longer calls Player::ViableEquipSlots(), update the patch")
    text = text.replace(OLD_SLOT_CALL, NEW_SLOT_CALL)

    for leftover in ("AllowableClass", "AllowableRace", "ViableEquipSlots",
                     "GetArmorAvailableForClass", "GetWeaponAvailableForClass"):
        if leftover in text:
            sys.exit("error: %s still present after patching" % leftover)

    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)

    print("patched: %s" % path)
    print("  any class/race may transmog any weapon or armor appearance")
    print("  only the inventory type -> equipment slot mapping remains")


if __name__ == "__main__":
    main()

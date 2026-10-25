// The Library button's single and long press reports. Traction's own: the layout is the one the 2026-10-25 device
// check wrote and the owner's ROG Xbox Ally X accepted (docs/notes/2026-10-24-remap-probe.md, Library press binding):
//   single = 5A D1 1D 01 12 + Library slot + Command Center slot
//   long   = 5A D1 23 01 12 + Library slot + Command Center slot
// A slot is 9 bytes, written as "05-00-1C-00-00-00-00-00-00":
//   ASUS action   05 00 <code> 00 00 00 00 00 00
//   key/shortcut  04 00 00 <n> k1..kn, then zeros (n 1..3)

using System;
using System.Collections.Generic;

namespace Traction.Helper
{
    public static class PressBindings
    {
        public const int SlotLength = 9;
        public const byte SingleCommand = 0x1D;
        public const byte LongCommand = 0x23;

        // The ASUS action codes the Library and Command Center buttons may run (Armoury Crate's own list).
        public static readonly byte[] FunctionCodes =
        {
            0x01, 0x02, 0x03, 0x04, 0x16, 0x17, 0x19, 0x1A, 0x1C, 0x1E, 0x26, 0x27, 0x28
        };

        // The key bytes (PS/2 set-2 codes and modifiers) of Bindings' allow-listed "02-xx" key codes and "04-n-k.."
        // shortcut codes, so the two lists cannot drift.
        public static readonly byte[] KeyCodes = KeysFromBindings();

        private static byte[] KeysFromBindings()
        {
            var keys = new List<byte>();
            foreach (string code in Bindings.Allowed)
            {
                string[] p = code.Split('-');
                int from = p[0] == "02" ? 1 : p[0] == "04" ? 2 : p.Length;
                for (int i = from; i < p.Length; i++)
                {
                    byte b = Convert.ToByte(p[i], 16);
                    if (b != 0 && !keys.Contains(b)) keys.Add(b);
                }
            }
            return keys.ToArray();
        }

        // Exactly 9 upper-case hex bytes joined by '-', in one of the two allowed shapes.
        public static bool IsAllowedSlot(string slot)
        {
            byte[] b = Parse(slot);
            if (b == null) return false;
            if (b[0] == 0x05)
            {
                if (b[1] != 0 || Array.IndexOf(FunctionCodes, b[2]) < 0) return false;
                return ZeroFrom(b, 3);
            }
            if (b[0] == 0x04)
            {
                int n = b[3];
                if (b[1] != 0 || b[2] != 0 || n < 1 || n > 3) return false;
                for (int i = 4; i < 4 + n; i++)
                    if (b[i] == 0 || Array.IndexOf(KeyCodes, b[i]) < 0) return false;
                return ZeroFrom(b, 4 + n);
            }
            return false;
        }

        // [5A D1 command 01 12] + the Library slot + the Command Center slot (23 bytes; padded when sent).
        public static byte[] Report(byte command, string library, string commandCenter)
        {
            if (command != SingleCommand && command != LongCommand)
                throw new ArgumentException("Unknown press report 0x" + command.ToString("X2") + ".");
            if (!IsAllowedSlot(library)) throw new ArgumentException("Unknown press binding '" + library + "'.");
            if (!IsAllowedSlot(commandCenter)) throw new ArgumentException("Unknown press binding '" + commandCenter + "'.");
            var r = new byte[5 + 2 * SlotLength];
            new byte[] { 0x5A, 0xD1, command, 0x01, 0x12 }.CopyTo(r, 0);
            Parse(library).CopyTo(r, 5);
            Parse(commandCenter).CopyTo(r, 5 + SlotLength);
            return r;
        }

        private static bool ZeroFrom(byte[] b, int start)
        {
            for (int i = start; i < b.Length; i++) if (b[i] != 0) return false;
            return true;
        }

        private static byte[] Parse(string slot)
        {
            if (slot == null || slot.Length != SlotLength * 3 - 1) return null;
            var b = new byte[SlotLength];
            for (int i = 0; i < SlotLength; i++)
            {
                int hi = Hex(slot[i * 3]), lo = Hex(slot[i * 3 + 1]);
                if (hi < 0 || lo < 0) return null;
                if (i < SlotLength - 1 && slot[i * 3 + 2] != '-') return null;
                b[i] = (byte)(hi * 16 + lo);
            }
            return b;
        }

        private static int Hex(char c)
        {
            if (c >= '0' && c <= '9') return c - '0';
            if (c >= 'A' && c <= 'F') return c - 'A' + 10;
            return -1;
        }
    }
}

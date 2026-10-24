// G-Helper - https://github.com/seerge/g-helper - app/Ally/AllyControl.cs
// Copyright seerge and contributors, licensed GPL-3.0. Commit c09017453d9ed0c52261b67a48d02bd55232e6ac.
// Modified for Traction (ported to C# 5 / .NET Framework 4.8), 2026
//
// Ported subset: the slot encoding of DecodeBinding, the zone report of BindZone ([0x5A,0xD1,0x02,zone,0x2C] and four
// 11-byte slots), the gamepad default bindings, InitInput ([0x5A] + "ASUS Tech.Inc."), the controller-on and Gamepad
// mode reports, and the turbo / deadzone / vibration reports G-Helper writes after the bindings (SetTurbo,
// SetDeadzones). The byte layout is the one the 2026-10-24 probe wrote on the owner's ROG Xbox Ally X
// (docs/notes/2026-10-24-remap-probe.md). The allow-list and the gamepad check are Traction's own.

using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;

namespace Traction.Helper
{
    // Which gamepads Windows sees. Injected so tests never touch XInput.
    public interface IPadCheck
    {
        // Bit i set = XInput pad i (0-3) is present.
        int Pads();
    }

    // XInput pads 0-3 (the Ally's built-in gamepad is pad 0 on the owner's device, but another pad may take index 0).
    // Read only; any failure counts as not present.
    public class XInputPadCheck : IPadCheck
    {
        [StructLayout(LayoutKind.Sequential)]
        private struct XInputGamepad { public ushort Buttons; public byte LeftTrigger, RightTrigger; public short LX, LY, RX, RY; }

        [StructLayout(LayoutKind.Sequential)]
        private struct XInputState { public uint PacketNumber; public XInputGamepad Gamepad; }

        [DllImport("xinput1_4.dll")]
        private static extern int XInputGetState(int userIndex, out XInputState state);

        public int Pads()
        {
            int mask = 0;
            for (int i = 0; i < 4; i++)
            {
                try
                {
                    XInputState s;
                    if (XInputGetState(i, out s) == 0) mask |= 1 << i;
                }
                catch (Exception) { }
            }
            return mask;
        }
    }

    public static class Bindings
    {
        public const int SlotLength = 11;

        public const string ResetMessage = "The controller stopped responding, so buttons were reset to the factory set.";

        // Every code set_bindings may write: Traction's action list (py_modules/traction/bindings.py ACTIONS), the
        // back buttons' Shift codes and every G-Helper gamepad and desktop default. tests/test_action_codes_match.py
        // checks this list against bindings.py.
        public static readonly string[] Allowed =
        {
            "00-00",
            "01-01", "01-02", "01-03", "01-04", "01-05", "01-06", "01-07", "01-08",
            "01-09", "01-0A", "01-0B", "01-0C", "01-0D", "01-0E", "01-11", "01-12",
            "02-0D", "02-29", "02-5A", "02-66", "02-76", "02-82", "02-88", "02-8E", "02-8F",
            "02-96", "02-97", "02-98", "02-99", "02-9A", "02-9B",
            "03-01", "03-02", "03-03", "03-04", "03-05",
            "04-02-82-0D", "04-02-82-23", "04-02-88-0D", "04-02-8A-0C", "04-02-8A-0D",
            "04-03-82-88-1B", "04-03-8C-88-76",
            "04-04-8C-88-8A-05", "04-04-8C-88-8A-06", "04-04-8C-88-8A-0C", "04-04-8C-88-8A-44",
            "05-02", "05-03", "05-19",
        };

        // G-Helper's gamepad defaults per zone (index 0 = zone 1), in slot order: first button, its combo, second
        // button, its combo.
        public static readonly string[][] GamepadDefaults = new string[][]
        {
            new[] { "01-09", "05-19", "01-0A", "04-02-82-23" },                     // 1 D-pad up / down
            new[] { "01-0B", "04-04-8C-88-8A-05", "01-0C", "04-04-8C-88-8A-06" },   // 2 D-pad left / right
            new[] { "01-07", "00-00", "01-08", "04-04-8C-88-8A-0C" },               // 3 stick clicks
            new[] { "01-05", "00-00", "01-06", "00-00" },                           // 4 LB / RB
            new[] { "01-01", "00-00", "01-02", "00-00" },                           // 5 A / B
            new[] { "01-03", "04-03-82-88-1B", "01-04", "04-04-8C-88-8A-44" },      // 6 X / Y
            new[] { "01-11", "00-00", "01-12", "00-00" },                           // 7 View / Menu
            new[] { "02-8E", "02-8E", "02-8F", "02-8F" },                           // 8 back buttons (M2, M1)
            new[] { "01-0D", "00-00", "01-0E", "00-00" },                           // 9 LT / RT
        };

        // The order the probe wrote the zones in on the device.
        private static readonly int[] FactoryZoneOrder = { 8, 1, 2, 3, 4, 5, 6, 7, 9 };

        public static bool IsAllowed(string code)
        {
            return code != null && Array.IndexOf(Allowed, code) >= 0;
        }

        // G-Helper DecodeBinding: "01 xx" -> byte 1, "02 xx" -> byte 2, "03 xx" -> byte 4, "05 xx" -> byte 3,
        // "04 n k1..kn" -> byte 0 = 04 and everything after the first byte from offset 5; "00-00" is all zero.
        public static byte[] Encode(string code)
        {
            var slot = new byte[SlotLength];
            string[] p = code.Split('-');
            var b = new byte[p.Length];
            for (int i = 0; i < p.Length; i++) b[i] = Convert.ToByte(p[i], 16);
            slot[0] = b[0];
            switch (b[0])
            {
                case 0x02: slot[2] = b[1]; break;
                case 0x03: slot[4] = b[1]; break;
                case 0x04: Array.Copy(b, 1, slot, 5, b.Length - 1); break;
                case 0x05: slot[3] = b[1]; break;
                default: slot[1] = b[1]; break;
            }
            return slot;
        }

        // [5A D1 02 zone 2C] + the four slots at offsets 5, 16, 27, 38 (49 bytes; padded when sent).
        public static byte[] ZoneReport(int zone, IList<string> slots)
        {
            var r = new byte[5 + 4 * SlotLength];
            new byte[] { 0x5A, 0xD1, 0x02, (byte)zone, 0x2C }.CopyTo(r, 0);
            for (int i = 0; i < 4; i++) Encode(slots[i]).CopyTo(r, 5 + i * SlotLength);
            return r;
        }

        // G-Helper's full factory set as the probe restored it: InitInput, controller on, Gamepad mode, every zone's
        // gamepad defaults, turbo off, deadzones, vibration 100 (and the second vibration report on the Xbox Ally).
        public static byte[][] FactoryReset(bool xbox)
        {
            var l = new List<byte[]>();
            var init = new byte[15];
            init[0] = 0x5A;
            System.Text.Encoding.ASCII.GetBytes("ASUS Tech.Inc.").CopyTo(init, 1);
            l.Add(init);
            l.Add(new byte[] { 0x5A, 0xD1, 0x0B, 0x01, 0x01 });
            l.Add(new byte[] { 0x5A, 0xD1, 0x01, 0x01, 0x01 });
            foreach (int z in FactoryZoneOrder) l.Add(ZoneReport(z, GamepadDefaults[z - 1]));
            l.Add(new byte[] { 0x5A, 0xD1, 0x0F, 0x20 });
            l.Add(new byte[] { 0x5A, 0xD1, 0x04, 0x04, 0x00, 0x64, 0x00, 0x64 });
            l.Add(new byte[] { 0x5A, 0xD1, 0x05, 0x04, 0x00, 0x64, 0x00, 0x64 });
            l.Add(new byte[] { 0x5A, 0xD1, 0x06, 0x02, 0x64, 0x64 });
            if (xbox) l.Add(new byte[] { 0x5A, 0xD1, 0x1C, 0x02, 0x64, 0x64 });
            return l.ToArray();
        }
    }
}

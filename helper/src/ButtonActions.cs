using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;

namespace Traction.Helper
{
    // One SendInput event: a key (virtual key, down or up, extended or not) or a mouse event (button flags or a wheel
    // step).
    public struct InputStep
    {
        public bool Mouse;
        public ushort Vk;
        public bool Up;
        public bool Extended;
        public uint MouseFlags;
        public int Wheel;
    }

    // The actions the Armoury Crate button can run (the ids and labels of bindings.ACTIONS in main.py, without the
    // gamepad buttons and the touch keyboard). Keys of a combo go down in the listed order and up in reverse.
    public static class ButtonActions
    {
        public static readonly string[] Ids =
        {
            "nothing", "mouse_left", "mouse_right", "mouse_middle", "scroll_up", "scroll_down", "esc", "enter", "tab",
            "backspace", "space", "up", "down", "left", "right", "page_up", "page_down", "win", "show_desktop",
            "screenshot", "task_manager", "close_window", "alt_tab", "win_tab", "volume_up", "volume_down"
        };

        // MOUSEEVENTF_* (winuser.h)
        public const uint MouseLeftDown = 0x0002, MouseLeftUp = 0x0004;
        public const uint MouseRightDown = 0x0008, MouseRightUp = 0x0010;
        public const uint MouseMiddleDown = 0x0020, MouseMiddleUp = 0x0040;
        public const uint MouseWheel = 0x0800;
        public const int WheelDelta = 120;

        // Arrows and Page Up/Down sit on the extended (E0) scan codes.
        private static readonly ushort[] ExtendedKeys = { 0x21, 0x22, 0x25, 0x26, 0x27, 0x28 };

        // The steps of an action; empty for "nothing", null for an unknown id.
        public static IList<InputStep> Steps(string id)
        {
            switch (id)
            {
                case "nothing": return new List<InputStep>();
                case "mouse_left": return Click(MouseLeftDown, MouseLeftUp);
                case "mouse_right": return Click(MouseRightDown, MouseRightUp);
                case "mouse_middle": return Click(MouseMiddleDown, MouseMiddleUp);
                case "scroll_up": return Scroll(WheelDelta);
                case "scroll_down": return Scroll(-WheelDelta);
                case "esc": return Keys(0x1B);
                case "enter": return Keys(0x0D);
                case "tab": return Keys(0x09);
                case "backspace": return Keys(0x08);
                case "space": return Keys(0x20);
                case "up": return Keys(0x26);
                case "down": return Keys(0x28);
                case "left": return Keys(0x25);
                case "right": return Keys(0x27);
                case "page_up": return Keys(0x21);
                case "page_down": return Keys(0x22);
                case "win": return Keys(0x5B);
                case "show_desktop": return Keys(0x5B, 0x44);          // Win+D
                case "screenshot": return Keys(0x5B, 0x10, 0x53);      // Win+Shift+S
                case "task_manager": return Keys(0x11, 0x10, 0x1B);    // Ctrl+Shift+Esc
                case "close_window": return Keys(0x12, 0x73);          // Alt+F4
                case "alt_tab": return Keys(0x12, 0x09);
                case "win_tab": return Keys(0x5B, 0x09);
                case "volume_up": return Keys(0xAF);
                case "volume_down": return Keys(0xAE);
            }
            return null;
        }

        // One string per step ("down 0x5B", "up 0x5B", "mouse left down", "wheel 120"); null for an unknown id.
        public static IList<string> Describe(string id)
        {
            IList<InputStep> steps = Steps(id);
            if (steps == null) return null;
            var l = new List<string>();
            foreach (InputStep s in steps) l.Add(DescribeStep(s));
            return l;
        }

        public static string DescribeStep(InputStep s)
        {
            if (!s.Mouse) return (s.Up ? "up 0x" : "down 0x") + s.Vk.ToString("X2");
            if ((s.MouseFlags & MouseWheel) != 0) return "wheel " + s.Wheel;
            switch (s.MouseFlags)
            {
                case MouseLeftDown: return "mouse left down";
                case MouseLeftUp: return "mouse left up";
                case MouseRightDown: return "mouse right down";
                case MouseRightUp: return "mouse right up";
                case MouseMiddleDown: return "mouse middle down";
                case MouseMiddleUp: return "mouse middle up";
            }
            return "mouse 0x" + s.MouseFlags.ToString("X");
        }

        private static IList<InputStep> Keys(params ushort[] vks)
        {
            var l = new List<InputStep>();
            foreach (ushort vk in vks) l.Add(Key(vk, false));
            for (int i = vks.Length - 1; i >= 0; i--) l.Add(Key(vks[i], true));
            return l;
        }

        private static InputStep Key(ushort vk, bool up)
        {
            return new InputStep { Vk = vk, Up = up, Extended = Array.IndexOf(ExtendedKeys, vk) >= 0 };
        }

        private static IList<InputStep> Click(uint down, uint up)
        {
            return new List<InputStep>
            {
                new InputStep { Mouse = true, MouseFlags = down },
                new InputStep { Mouse = true, MouseFlags = up, Up = true }
            };
        }

        private static IList<InputStep> Scroll(int delta)
        {
            return new List<InputStep> { new InputStep { Mouse = true, MouseFlags = MouseWheel, Wheel = delta } };
        }
    }

    public interface IInputSender
    {
        void Send(IList<InputStep> steps);
    }

    // SendInput (user32). x64 layout: INPUT is 40 bytes (type, 4 bytes of padding, the 32-byte MOUSEINPUT union).
    // All steps of an action go in one call, so nothing else is interleaved between them.
    public sealed class Win32InputSender : IInputSender
    {
        private const uint INPUT_MOUSE = 0;
        private const uint INPUT_KEYBOARD = 1;
        private const uint KEYEVENTF_EXTENDEDKEY = 0x0001;
        private const uint KEYEVENTF_KEYUP = 0x0002;

        [StructLayout(LayoutKind.Sequential)]
        private struct MOUSEINPUT
        {
            public int dx;
            public int dy;
            public int mouseData;
            public uint dwFlags;
            public uint time;
            public IntPtr dwExtraInfo;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct KEYBDINPUT
        {
            public ushort wVk;
            public ushort wScan;
            public uint dwFlags;
            public uint time;
            public IntPtr dwExtraInfo;
        }

        [StructLayout(LayoutKind.Explicit)]
        private struct InputUnion
        {
            [FieldOffset(0)] public MOUSEINPUT mi;
            [FieldOffset(0)] public KEYBDINPUT ki;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct INPUT
        {
            public uint type;
            public InputUnion u;
        }

        [DllImport("user32.dll", SetLastError = true)]
        private static extern uint SendInput(uint nInputs, [In] INPUT[] pInputs, int cbSize);

        // Marshalled size of INPUT, for the layout test (x64: 40).
        public static int InputSize() { return Marshal.SizeOf(typeof(INPUT)); }

        public void Send(IList<InputStep> steps)
        {
            if (steps == null || steps.Count == 0) return;
            var inputs = new INPUT[steps.Count];
            for (int i = 0; i < steps.Count; i++)
            {
                InputStep s = steps[i];
                if (s.Mouse)
                {
                    inputs[i].type = INPUT_MOUSE;
                    inputs[i].u.mi.dwFlags = s.MouseFlags;
                    inputs[i].u.mi.mouseData = s.Wheel;
                }
                else
                {
                    inputs[i].type = INPUT_KEYBOARD;
                    inputs[i].u.ki.wVk = s.Vk;
                    inputs[i].u.ki.dwFlags = (s.Up ? KEYEVENTF_KEYUP : 0) | (s.Extended ? KEYEVENTF_EXTENDEDKEY : 0);
                }
            }
            uint sent = SendInput((uint)inputs.Length, inputs, InputSize());
            if (sent != inputs.Length)
                throw new InvalidOperationException("SendInput sent " + sent + " of " + inputs.Length + " events (error "
                    + Marshal.GetLastWin32Error() + ").");
        }
    }
}

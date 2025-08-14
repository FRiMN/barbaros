#!/usr/bin/env python3
import Xlib.display

def test_xlib():
    try:
        display = Xlib.display.Display()
        print("X server connection successful")
    except Exception as e:
        print(f"X protocol error: {e}")

if __name__ == "__main__":
    test_xlib()

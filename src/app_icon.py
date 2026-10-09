"""Install the shared app icon, including the running macOS application."""
import ctypes
import sys
import tkinter as tk


def install_app_icon(root, path):
    if not path.is_file():
        return
    # Keep the Tk image alive for the lifetime of the app.
    root.app_icon = tk.PhotoImage(master=root, file=str(path))
    root.iconphoto(True, root.app_icon)
    if sys.platform == "darwin":
        _set_macos_icon(path)


def _set_macos_icon(path):
    # Older Tk builds do not reliably update the Dock icon. AppKit is already
    # loaded by Tk; use its public applicationIconImage property directly.
    objc = ctypes.CDLL("/usr/lib/libobjc.A.dylib")
    pointer = ctypes.c_void_p
    objc.objc_getClass.argtypes = [ctypes.c_char_p]
    objc.objc_getClass.restype = pointer
    objc.sel_registerName.argtypes = [ctypes.c_char_p]
    objc.sel_registerName.restype = pointer
    selector = objc.sel_registerName
    send = ctypes.CFUNCTYPE(pointer, pointer, pointer)(("objc_msgSend", objc))
    send_object = ctypes.CFUNCTYPE(pointer, pointer, pointer, pointer)(("objc_msgSend", objc))
    send_string = ctypes.CFUNCTYPE(pointer, pointer, pointer, ctypes.c_char_p)(("objc_msgSend", objc))
    set_object = ctypes.CFUNCTYPE(None, pointer, pointer, pointer)(("objc_msgSend", objc))
    release = ctypes.CFUNCTYPE(None, pointer, pointer)(("objc_msgSend", objc))
    filename = send_string(objc.objc_getClass(b"NSString"), selector(b"stringWithUTF8String:"), str(path).encode("utf-8"))
    icon = send(objc.objc_getClass(b"NSImage"), selector(b"alloc"))
    icon = send_object(icon, selector(b"initWithContentsOfFile:"), filename)
    if not icon:
        return
    try:
        application = send(objc.objc_getClass(b"NSApplication"), selector(b"sharedApplication"))
        set_object(application, selector(b"setApplicationIconImage:"), icon)
    finally:
        release(icon, selector(b"release"))

# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files

datas = []
datas += collect_data_files('customtkinter')

a = Analysis(
    ['coworksync/main.py'],
    pathex=[],
    binaries=[],
    datas=datas + [
        ('coworksync/assets', 'coworksync/assets'),
    ],
    hiddenimports=[
        'watchdog.observers.winapi',
        'pystray._win32',
        'PIL._tkinter_finder',
        'customtkinter',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='CoworkSync',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='coworksync/assets/icon_green.ico',
)

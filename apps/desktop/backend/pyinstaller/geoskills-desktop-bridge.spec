from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


ROOT = Path(SPECPATH).resolve().parents[3]
BACKEND = ROOT / "apps" / "desktop" / "backend"
SCRIPTS = ROOT / "skills" / "geoskills" / "scripts"
ASSETS = ROOT / "skills" / "geoskills" / "assets"

dynamic_handlers = [
    "inspect_data",
    "inspect_spider_data",
    "inspect_major_data",
    "plot_ree",
    "plot_spider",
    "plot_harker",
    "plot_tas",
    "plot_k2o_sio2",
    "plot_xy",
    "normalize_ree",
    "normalize_spider",
    "matplotlib.backends.backend_agg",
    "matplotlib.backends.backend_pdf",
    "matplotlib.backends.backend_svg",
    "PIL.TiffImagePlugin",
]
hidden_imports = sorted(set(dynamic_handlers + collect_submodules("geoskills_core")))
scientific_assets = [
    (str(ASSETS / "normalization"), "skills/geoskills/assets/normalization"),
    (str(ASSETS / "classification"), "skills/geoskills/assets/classification"),
]

a = Analysis(
    [str(BACKEND / "geoskills_desktop_bridge.py")],
    pathex=[str(BACKEND), str(SCRIPTS)],
    binaries=[],
    datas=scientific_assets,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="geoskills-desktop-bridge-x86_64-pc-windows-msvc",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

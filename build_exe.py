# -*- coding: utf-8 -*-
"""
ساخت فایل اجرایی ویندوز — نسخه‌ی پایتونی (پیشنهادی)
====================================================
این اسکریپت جایگزینِ مطمئن‌تری برای build_windows.bat است، چون به
«کدپیجِ cmd»، «نوعِ خطِ پایان» و «نبودنِ pyinstaller در PATH» حساس نیست.

اجرا:
    python build_exe.py              نسخه‌ی پوشه‌ای (سریع‌تر، مطمئن‌تر)
    python build_exe.py --onefile    یک فایل exe ی یکپارچه
    python build_exe.py --console    همراه با پنجره‌ی کنسول (برای عیب‌یابی)
    python build_exe.py --dry-run    فقط نمایشِ فرمان (بدون نصب و ساخت)
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP_NAME = "Hesabdar"
HIDDEN = [
    "PySide6.QtPrintSupport",
    "PySide6.QtWidgets",
    "PySide6.QtSvg",
    "schema_embedded",
]


def run(cmd, check=True):
    """اجرای یک دستور با نمایشِ زنده‌ی خروجی"""
    print(f"\n▸ {' '.join(cmd)}\n{'-' * 60}")
    result = subprocess.run(cmd, cwd=HERE)
    if check and result.returncode != 0:
        print(f"\n❌ دستور با کد {result.returncode} شکست خورد")
        sys.exit(result.returncode)
    return result.returncode


def ensure_module(module_name: str, import_name: str = ""):
    """نصب یک بسته در صورت نبودن"""
    try:
        __import__(import_name or module_name)
        print(f"✓ {module_name} از پیش نصب است")
        return
    except ImportError as e:
        print(f"  (یادداشت: بررسیِ {module_name} ناموفق بود: {e})")
    print(f"▸ در حال نصب {module_name} …")
    if run([sys.executable, "-m", "pip", "install", "--user", module_name], check=False) != 0:
        # تلاشِ دوم بدون --user (محیط‌های مجازی / نصبِ سراسری)
        if run([sys.executable, "-m", "pip", "install", module_name], check=False) != 0:
            print(f"\n❌ نصبِ {module_name} ناموفق بود.")
            print("   اگر پشت پروکسی هستید یا اینترنت قطع است، دستی نصب کنید:")
            print(f"   {sys.executable} -m pip install {module_name}")
            sys.exit(1)


def embed_schema():
    """
    جاسازیِ schema.sql داخل یک ماژول پایتونی.
    این کار تضمین می‌کند که حتی اگر فایل schema.sql در بسته‌ی اجرایی
    گم شود، برنامه بتواند پایگاه داده را بسازد.
    """
    src = os.path.join(HERE, "schema.sql")
    dst = os.path.join(HERE, "schema_embedded.py")
    with open(src, encoding="utf-8") as f:
        sql = f.read()
    with open(dst, "w", encoding="utf-8") as f:
        f.write("# -*- coding: utf-8 -*-\n")
        f.write('"""نسخه‌ی جاسازی‌شده‌ی schema.sql — به صورت خودکار ساخته شده است.\n')
        f.write('   این فایل را دستی ویرایش نکنید؛ فایل اصلی schema.sql است."""\n\n')
        f.write("SCHEMA_SQL = r'''\n" + sql + "\n'''\n")
    print(f"✓ schema.sql در schema_embedded.py جاسازی شد ({len(sql):,} کاراکتر)")


def main():
    onefile = "--onefile" in sys.argv
    console = "--console" in sys.argv
    dry_run = "--dry-run" in sys.argv

    print("=" * 60)
    print(f"  ساخت {APP_NAME}.exe  —  Python {sys.version.split()[0]}")
    print("=" * 60)

    if not os.path.exists(os.path.join(HERE, "main.py")):
        print("❌ فایل main.py در این پوشه یافت نشد")
        sys.exit(1)

    if not dry_run:
        embed_schema()
    if dry_run:
        print("\n[حالت آزمایشی] نصب بسته‌ها و جاسازی schema نادیده گرفته شد.")
    else:
        ensure_module("PySide6", "PySide6")
        ensure_module("pyinstaller", "PyInstaller")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--name", APP_NAME,
        "--add-data", os.path.join(HERE, "schema.sql") + os.pathsep + ".",
        "--add-data", os.path.join(HERE, "assets") + os.pathsep + "assets",
    ]
    for h in HIDDEN:
        cmd += ["--hidden-import", h]
    cmd += ["--console" if console else "--windowed"]
    if onefile:
        cmd.append("--onefile")
    cmd.append(os.path.join(HERE, "main.py"))

    if dry_run:
        print("\n[حالت آزمایشی] فرمانِ ساخت:")
        print("  " + " ".join(cmd))
        return

    run(cmd)

    name = f"{APP_NAME}.exe" if os.name == "nt" else APP_NAME
    if onefile:
        exe = os.path.join(HERE, "dist", name)
    else:
        exe = os.path.join(HERE, "dist", APP_NAME, name)

    print("\n" + "=" * 60)
    if os.path.exists(exe):
        size = os.path.getsize(exe) / (1024 * 1024)
        print(f"✅ ساخته شد: {exe}  ({size:.1f} مگابایت)")
        if onefile:
            print("\nنکته: حالت یکپارچه در اولین اجرا کمی کندتر است")
            print("      (فایل‌ها در پوشه‌ی موقت استخراج می‌شوند).")
    else:
        print("⚠️  ساخت پایان یافت اما فایل exe پیدا نشد؛")
        print("    خروجی‌های PyInstaller را در پوشه‌ی dist بررسی کنید.")
    print("=" * 60)
    print("\nبرای اجرا:  " + exe)


if __name__ == "__main__":
    main()

import ast
import importlib.util
import subprocess
import sys
import stdlib_list
from perplexity import Perplexity
from dotenv import load_dotenv
import os
import re

# =============================
# CONFIG
# =============================

load_dotenv()  # Load environment variables from .env file

perplexity_api_key = os.getenv("PERPLEXITY_API_KEY")

client = Perplexity()

# Predefined mapping for common mismatches
COMMON_MAP = {
    "bs4": "beautifulsoup4",
    "cv2": "opencv-python",
    "sklearn": "scikit-learn",
    "PIL": "pillow",
    "yaml": "pyyaml",
    "Crypto": "pycryptodome"
}

# =============================
# CORE FUNCTIONS
# =============================

def extract_imports(file_path: str) -> set:
    """Extract top-level import names from a Python file."""
    with open(file_path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=file_path)

    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module.split(".")[0])
    return imports


def ask_ai_for_package(module: str, context: str = "") -> str:
    """Ask AI to suggest the correct PyPI package (must be pip-installable)."""
    try:
        resp = client.chat.completions.create(
            model="sonar",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a Python packaging assistant. "
                        "When asked for a package, respond ONLY with a valid 'pip install <package>' command "
                        "using the exact PyPI package name. Do not invent names like 'python-<pkg>'."
                    )
                },
                {
                    "role": "user",
                    "content": f"The Python module '{module}' failed. {context}\n"
                               f"Which exact PyPI package should be installed? Reply only with: pip install <package>"
                }
            ]
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"⚠️ AI request failed: {e}")
        return None


def resolve_package(module: str) -> str:
    """Resolve module name to PyPI package name."""
    if module in COMMON_MAP:
        return COMMON_MAP[module]
    return module


def try_install(package: str, module: str) -> bool:
    """Attempt to install a package via pip. Return True if successful, False if not."""
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])
        print(f"✅ Installed {package}")
        return True
    except FileNotFoundError:
        print("❌ pip not found in this environment. Run:")
        print("   python -m ensurepip --upgrade")
        print("   python -m pip install --upgrade pip")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Failed to install {package} for module '{module}': {e}")
        return False


def is_real_pypi_package(pkg: str) -> bool:
    """Check if package exists on PyPI by attempting a dry-run install."""
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--dry-run", pkg],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        return True
    except subprocess.CalledProcessError:
        return False


def install_missing(imports: set):
    """Check and install missing packages from a set of imports."""
    version_str = f"{sys.version_info.major}.{sys.version_info.minor}"
    stdlib = set(stdlib_list.stdlib_list(version_str))

    for module in imports:
        if module in stdlib:
            print(f"✅ {module} is part of Python stdlib")
            continue

        if importlib.util.find_spec(module) is None:
            package = resolve_package(module)
            print(f"📦 Installing {package} for module '{module}'...")
            success = try_install(package, module)

            if not success:
                ai_suggestion = ask_ai_for_package(module, "Suggest a valid PyPI package replacement.")
                if ai_suggestion:
                    match = re.search(r"pip install ([\w\-]+)", ai_suggestion)
                    suggested_pkg = match.group(1) if match else None

                    # Retry until we get a real PyPI package
                    if suggested_pkg and not is_real_pypi_package(suggested_pkg):
                        print(f"⚠️ '{suggested_pkg}' is not a real PyPI package. Asking AI again...")
                        ai_suggestion = ask_ai_for_package(
                            module,
                            "Your last answer was invalid. Give only a valid PyPI package name."
                        )
                        match = re.search(r"pip install ([\w\-]+)", ai_suggestion or "")
                        suggested_pkg = match.group(1) if match else None

                    # Handle deprecated/broken installs
                    if suggested_pkg and is_real_pypi_package(suggested_pkg):
                        if not try_install(suggested_pkg, module):
                            print(f"⚠️ '{suggested_pkg}' exists but failed to install. Asking AI for a replacement...")
                            ai_suggestion = ask_ai_for_package(
                                module,
                                f"The package '{suggested_pkg}' exists but fails to install. Suggest the modern supported replacement."
                            )
                            match = re.search(r"pip install ([\w\-]+)", ai_suggestion or "")
                            suggested_pkg = match.group(1) if match else None

                        if suggested_pkg and is_real_pypi_package(suggested_pkg):
                            print(f"\n🤖 AI suggests: {ai_suggestion}")
                            choice = input(f"👉 Do you want to install '{suggested_pkg}' instead of '{module}'? (Y/n): ").strip().lower()
                            if choice == "y" or choice == "Y" :
                                try_install(suggested_pkg, module)
                            else:
                                print(f"⏭️ Skipped installing alternative for '{module}'")
                        else:
                            print(f"⚠️ No valid package name found in AI suggestion for '{module}'. Skipping.")
        else:
            print(f"✅ {module} already installed")


# =============================
# ENTRY POINT
# =============================
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python main.py <your_script.py>")
        sys.exit(1)

    file_path = sys.argv[1]
    imports = extract_imports(file_path)
    print("🔍 Found imports:", imports)
    install_missing(imports)

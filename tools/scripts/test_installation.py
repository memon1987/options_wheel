#!/usr/bin/env python3
"""Test script to verify all required packages are properly installed."""

import sys
import importlib
from typing import Dict, List, Tuple

def test_import(module_name: str, package_name: str = None) -> Tuple[bool, str]:
    """Test if a module can be imported.
    
    Args:
        module_name: Name of module to import
        package_name: Package name for error messages (if different)
        
    Returns:
        Tuple of (success, error_message)
    """
    try:
        importlib.import_module(module_name)
        return True, ""
    except ImportError as e:
        pkg_name = package_name or module_name
        return False, f"❌ {pkg_name}: {str(e)}"

def main():
    """Run installation tests."""
    print("🔍 Testing Options Wheel Strategy Installation")
    print("=" * 50)
    
    # Core packages (essential)
    core_packages = [
        ("pandas", None),
        ("numpy", None),
        ("scipy", None),
        ("yaml", "pyyaml"),
        ("dotenv", "python-dotenv"),
        ("requests", None),
        ("structlog", None),
        ("pytest", None),
        ("alpaca", "alpaca-py"),
        ("openpyxl", None),
    ]
    
    # Visualization packages
    viz_packages = [
        ("matplotlib", None),
        ("matplotlib.pyplot", "matplotlib"),
        ("seaborn", None),
        ("plotly", None),
    ]
    
    # Optional packages
    optional_packages = [
        ("jupyter", None),
        ("streamlit", None),
        ("statsmodels", None),
        ("yfinance", None),
        ("click", None),
        ("tqdm", None),
    ]
    
    # Test core packages
    print("🔧 CORE PACKAGES")
    print("-" * 20)
    core_failed = []
    for module, package in core_packages:
        success, error = test_import(module, package)
        if success:
            print(f"✅ {package or module}")
        else:
            print(error)
            core_failed.append(package or module)
    
    # Test visualization packages
    print(f"\n🎨 VISUALIZATION PACKAGES")
    print("-" * 25)
    viz_failed = []
    for module, package in viz_packages:
        success, error = test_import(module, package)
        if success:
            print(f"✅ {package or module}")
        else:
            print(error)
            viz_failed.append(package or module)
    
    # Test optional packages
    print(f"\n⭐ OPTIONAL PACKAGES")
    print("-" * 20)
    optional_failed = []
    for module, package in optional_packages:
        success, error = test_import(module, package)
        if success:
            print(f"✅ {package or module}")
        else:
            print(f"⚠️  {package or module}: Not installed (optional)")
            optional_failed.append(package or module)
    
    # Test project modules
    print(f"\n🏗️  PROJECT MODULES")
    print("-" * 18)
    
    # Add src to path for testing
    import os
    script_dir = os.path.dirname(__file__)
    project_root = os.path.dirname(script_dir)  # Go up one level from scripts/
    sys.path.insert(0, os.path.join(project_root, 'src'))
    
    project_modules = [
        "utils.config",
        "api.alpaca_client",
        "strategy.wheel_engine",
        "backtesting.backtest_engine",
        "risk.risk_manager",
    ]
    
    project_failed = []
    for module in project_modules:
        success, error = test_import(module)
        module_name = module.split('.')[-1]
        if success:
            print(f"✅ {module_name}")
        else:
            print(f"❌ {module_name}: {error}")
            project_failed.append(module_name)
    
    # Summary
    print(f"\n" + "=" * 50)
    print("📊 INSTALLATION SUMMARY")
    print("=" * 50)
    
    if not core_failed and not project_failed:
        print("🎉 SUCCESS: All essential packages installed correctly!")
        
        if viz_failed:
            print(f"⚠️  WARNING: {len(viz_failed)} visualization packages missing:")
            for pkg in viz_failed:
                print(f"   - {pkg}")
            print("   Install with: pip install matplotlib seaborn plotly")
        else:
            print("✅ All visualization packages available")
        
        if optional_failed:
            print(f"ℹ️  INFO: {len(optional_failed)} optional packages not installed")
        
        print(f"\n🚀 READY TO USE:")
        print(f"   - Live trading: python main.py --command scan")
        print(f"   - Backtesting: python demo_backtest.py")
        print(f"   - Run tests: python -m pytest tests/ -v")
        
        return 0
        
    else:
        print("❌ INSTALLATION ISSUES FOUND")
        
        if core_failed:
            print(f"\n🔴 CRITICAL: Missing core packages:")
            for pkg in core_failed:
                print(f"   - {pkg}")
            print("   Install with: pip install -r requirements-minimal.txt")
        
        if project_failed:
            print(f"\n🔴 CRITICAL: Project module issues:")
            for module in project_failed:
                print(f"   - {module}")
            print("   Check your Python path and src/ directory structure")
        
        print(f"\n💡 INSTALLATION COMMANDS:")
        print(f"   Full install: pip install -r requirements.txt")
        print(f"   Minimal:      pip install -r requirements-minimal.txt")
        print(f"   Development:  pip install -r requirements-dev.txt")
        
        return 1

if __name__ == "__main__":
    sys.exit(main())
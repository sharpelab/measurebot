# Build and Distribution Script for MeasureBot
# Run this to create distribution packages

import subprocess
import sys
import os

def run_command(cmd, description):
    """Run a command and print the result."""
    print(f"\n{'='*50}")
    print(f"Running: {description}")
    print(f"Command: {cmd}")
    print(f"{'='*50}")
    
    try:
        result = subprocess.run(cmd, shell=True, check=True, capture_output=True, text=True)
        print("✅ Success!")
        if result.stdout:
            print("Output:", result.stdout)
        return True
    except subprocess.CalledProcessError as e:
        print("❌ Failed!")
        print("Error:", e.stderr)
        return False

def main():
    """Build the package for distribution."""
    
    # Check if we're in the right directory
    if not os.path.exists("setup.py"):
        print("❌ Error: setup.py not found. Run this script from the measurebot root directory.")
        return
    
    # Install build dependencies
    print("Installing build dependencies...")
    run_command(f"{sys.executable} -m pip install --upgrade build twine", "Installing build tools")
    
    # Clean old builds
    if os.path.exists("dist"):
        import shutil
        shutil.rmtree("dist")
        print("🧹 Cleaned old dist directory")
    
    if os.path.exists("measurebot.egg-info"):
        import shutil
        shutil.rmtree("measurebot.egg-info")
        print("🧹 Cleaned old egg-info directory")
    
    # Build the package
    if run_command(f"{sys.executable} -m build", "Building distribution packages"):
        print("\n✅ Package built successfully!")
        print("📦 Distribution files created in ./dist/")
        
        if os.path.exists("dist"):
            dist_files = os.listdir("dist")
            for file in dist_files:
                print(f"   - {file}")
        
        print("\n📋 Next steps:")
        print("1. To install locally: pip install dist/measurebot-0.1.0-py3-none-any.whl")
        print("2. To upload to PyPI: twine upload dist/*")
        print("3. To install from GitHub: pip install git+https://github.com/sharpelab/measurebot.git")
    else:
        print("❌ Build failed!")

if __name__ == "__main__":
    main()
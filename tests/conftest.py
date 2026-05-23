import sys
import os
import importlib.util

class ControlPlaneFinder:
    def find_spec(self, fullname, path, target=None):
        if fullname == "control_plane" or fullname.startswith("control_plane."):
            # Map "control_plane" to "control-plane" directory
            root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            parts = fullname.split(".")
            parts[0] = "control-plane"
            
            # construct actual path
            target_dir = os.path.join(root, *parts[:-1])
            name = parts[-1]
            
            pkg_path = os.path.join(target_dir, name, "__init__.py")
            mod_path = os.path.join(target_dir, f"{name}.py")
            
            if os.path.exists(pkg_path):
                return importlib.util.spec_from_file_location(
                    fullname, 
                    pkg_path, 
                    submodule_search_locations=[os.path.dirname(pkg_path)]
                )
            elif os.path.exists(mod_path):
                return importlib.util.spec_from_file_location(fullname, mod_path)
        return None

sys.meta_path.insert(0, ControlPlaneFinder())

"""Checks that every function named in CODE_FLOW.md really exists in the code."""
import re

FILES = ["user_context.py", "gemini_code_fixed.py", "layout_catalogue.py", "layout_engine.py",
         "layout_templates.py", "imp_functions.py", "def_prompts.py", "comfyui.py",
         "generate_layout_templates.py", "generate_code_flow_diagram.py"]

defined = set()
for f in FILES:
    src = open(f, encoding="utf-8").read()
    for m in re.finditer(r"^\s*def\s+([A-Za-z_][A-Za-z0-9_]*)", src, re.M):
        defined.add(m.group(1))
    for m in re.finditer(r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)", src, re.M):
        defined.add(m.group(1))

doc = open("CODE_FLOW.md", encoding="utf-8").read() + open("generate_code_flow_diagram.py", encoding="utf-8").read()
names = set(re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\(\)", doc))

# names that belong to the app but are not functions of ours
external = {"str", "int", "float", "bool", "list", "dict", "set", "tuple", "print", "len",
            "open", "os", "json", "gr", "glob", "copy", "re", "math", "sorted",
            # method calls on other objects (gr.Blocks, dict.clear, ...create, .items, .split)
            "Blocks", "clear", "create", "items", "split"}
missing = sorted(n for n in names if n not in defined and n not in external)

print(f"functions referenced in the docs : {len(names) - len(external & names)}")
print(f"defined in the code               : {len(defined)}")
if missing:
    print("MISSING from the code            :", missing)
else:
    print("MISSING from the code            : none - all verified")

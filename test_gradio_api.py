"""Drives the running Gradio app through its real API (gradio_client)."""
import sys

sys.path.insert(0, r"C:\Users\User\Documents\GitHub\deckmaker")

from gradio_client import Client

client = Client("http://127.0.0.1:7860/", verbose=False)

print("API endpoints:")
api = client.view_api(return_format="dict")
for name, spec in list(api.get("named_endpoints", {}).items()):
    print(f"  - {name}: {len(spec.get('parameters', []))} params -> {len(spec.get('returns', []))} returns")

print("\nUnnamed endpoints:", len(api.get("unnamed_endpoints", {})))
for i, (name, spec) in enumerate(api.get("unnamed_endpoints", {}).items()):
    if i > 40:
        break
    print(f"  [{i}] {name}: {[p.get('label') for p in spec.get('parameters', [])][:3]}")

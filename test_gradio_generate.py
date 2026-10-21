"""Calls the real 'Generate slide' endpoint of the running Gradio app."""
import sys

sys.path.insert(0, r"C:\Users\User\Documents\GitHub\deckmaker")

from gradio_client import Client

client = Client("http://127.0.0.1:7860/", verbose=False)

print("Calling /handler_1 (Generate slide 1) with the L05 metrics template ...")
result = client.predict(
    title="Quarterly results",
    content="Revenue grew 27% year on year. Gross margin fell from 62% to 58%. "
            "Churn is flat at 3.1%. Enterprise now drives 44% of revenue, up from 29%.",
    layout="L05 · Big Numbers Metric",
    model_selection="gpt-oss",
    api_name="/handler_1",
)

title, content, layout, image, status = result
print("\n--- returned ---")
print("title   :", title)
print("layout  :", layout)
print("image   :", image)
print("content :")
for line in str(content).splitlines():
    print("   ", line)
print("status  :")
for line in str(status).splitlines():
    print("   ", line)

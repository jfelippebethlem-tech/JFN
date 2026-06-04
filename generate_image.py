from diffusers import StableDiffusionPipeline
import torch
import os

prompt = "a blonde girl with blue eyes, rollerblading in the middle of an Outback restaurant, highly detailed, realistic, cinematic lighting"
negative_prompt = "ugly, deformed, disfigured, poor quality, bad anatomy, bad hands, blurry, low resolution, worse quality"
output_path = "/app/generated_image.png"

# Load the model - using a smaller, CPU-friendly model for this environment
# Note: This will download the model, which can take some time.
model_id = "runwayml/stable-diffusion-v1-5"
pipe = StableDiffusionPipeline.from_pretrained(model_id, torch_dtype=torch.float32)

# Ensure it's running on CPU
pipe.to("cpu")

# Generate image
image = pipe(prompt=prompt, negative_prompt=negative_prompt, num_inference_steps=25).images[0]

# Save the image
image.save(output_path)
print(f"Image generated and saved to {output_path}")

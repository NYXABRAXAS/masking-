from fastapi import FastAPI, File, UploadFile, Header, HTTPException, Depends
from fastapi.responses import FileResponse
from starlette.background import BackgroundTasks

import pytesseract
from PIL import Image
import cv2
import re
import os
import json
import tempfile

app = FastAPI(title="Aadhaar OCR & Masking API")

# ---------------- API KEY ----------------
API_KEYS = ["mysecretkey123"]

def verify_api_key(x_api_key: str = Header(None)):
    if not x_api_key or x_api_key not in API_KEYS:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    return x_api_key

# ---------------- CLEANUP ----------------
def remove_file(path: str):
    if os.path.exists(path):
        os.remove(path)

# ---------------- HELPER ----------------
def clean_name(value):
    if not value:
        return value
    value = re.sub(r'[^A-Za-z\s]', '', value)
    words = [w for w in value.split() if len(w) > 1]
    return " ".join(words)

# ---------------- MAIN API ----------------
@app.post("/v1/ocr/extract-and-mask")
async def extract_and_mask(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    x_api_key: str = Depends(verify_api_key)
):

    if file.content_type not in ["image/jpeg", "image/png", "image/jpg"]:
        raise HTTPException(400, "Only image files allowed")

    # Save temp file
    suffix = os.path.splitext(file.filename)[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        input_path = tmp.name

    try:
        # ---------------- OCR ----------------
        image = Image.open(input_path)
        full_text = pytesseract.image_to_string(image)

        lines = full_text.split("\n")

        # ---------------- EXTRACTION ----------------
        extracted = {
            "aadhaar_number": None,
            "dob": None,
            "name": None
        }

        # Aadhaar Number
        num_match = re.search(r'\b\d{4}\s?\d{4}\s?\d{4}\b', full_text)
        if num_match:
            extracted["aadhaar_number"] = num_match.group(0)

        # DOB
        dob_match = re.search(r'\d{2}/\d{2}/\d{4}', full_text)
        if dob_match:
            extracted["dob"] = dob_match.group(0)

        # Name (simple logic)
        for i, line in enumerate(lines):
            if "GOVERNMENT" in line.upper() or "INDIA" in line.upper():
                for j in range(1, 4):
                    if i + j < len(lines):
                        candidate = lines[i + j]
                        if len(candidate.split()) >= 2 and not any(c.isdigit() for c in candidate):
                            extracted["name"] = clean_name(candidate)
                            break
                if extracted["name"]:
                    break

        # ---------------- MASKING ----------------
        img = cv2.imread(input_path)

        if extracted["aadhaar_number"]:
            # Find Aadhaar pattern in image (approx masking)
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            h, w = img.shape[:2]

            # Mask bottom area (where Aadhaar usually present)
            cv2.rectangle(img, (0, int(h * 0.6)), (w, h), (0, 0, 0), -1)

        # Save masked image
        output_path = input_path.replace(suffix, f"_masked{suffix}")
        cv2.imwrite(output_path, img)

        # ---------------- RESPONSE ----------------
        headers = {
            "X-OCR-Data": json.dumps(extracted),
            "Access-Control-Expose-Headers": "X-OCR-Data"
        }

        background_tasks.add_task(remove_file, input_path)
        background_tasks.add_task(remove_file, output_path)

        return FileResponse(
            path=output_path,
            media_type=file.content_type,
            filename=f"masked_{file.filename}",
            headers=headers
        )

    except Exception as e:
        remove_file(input_path)
        raise HTTPException(500, str(e))


@app.get("/")
def home():
    return {"status": "OCR & Masking API Running 🚀"}

import streamlit as st
from PIL import Image, ImageEnhance
import pytesseract
from deep_translator import GoogleTranslator
import re
import os
from langdetect import detect
import uuid
import logging
import io

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Tesseract configuration
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

def preprocess_image_for_ocr(image):
    """Preprocesses image for better OCR results."""
    try:
        # Convert to grayscale
        img = image.convert('L')
        # Increase contrast
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(2.0)
        # Basic thresholding (binarization)
        img = img.point(lambda p: 255 if p > 150 else 0)
        return img
    except Exception as e:
        logging.error(f"Error preprocessing image: {e}")
        raise

def extract_text_from_image(image_obj, lang='eng'):
    """Extracts text from image using Tesseract with optimized settings."""
    try:
        custom_config = r'--oem 3 --psm 6'
        text = pytesseract.image_to_string(image_obj, lang=lang, config=custom_config)
        if not text.strip():
            return None, "OCR detected no text. Try a clearer image or adjust OCR settings."
        return text, None
    except pytesseract.TesseractNotFoundError:
        return None, "Tesseract not found. Ensure it's installed and in PATH."
    except Exception as e:
        return None, f"Error during OCR: {e}"

def translate_text_to_english(text, source_lang='auto'):
    """Translates text to English using GoogleTranslator."""
    if not text:
        return ""
    try:
        translated_text = GoogleTranslator(source=source_lang, target='en').translate(text)
        return translated_text if translated_text else text
    except Exception as e:
        logging.error(f"Translation error: {e}")
        return text

def is_likely_phone_number(text):
    """Checks if text resembles a phone number."""
    phone_pattern = r'(\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b'
    return bool(re.search(phone_pattern, text))

def parse_medicine_details(text):
    """Parses medicine details from text."""
    medicines = []
    lines = text.split('\n')
    current_medicine_name = None

    dosage_keywords = ['mg', 'ml', 'g', 'mcg', 'tablet', 'capsule', 'spoon', 'drops', 'puff']
    frequency_keywords = [
        'daily', 'once a day', 'twice a day', 'thrice a day', 'times a day',
        'bd', 'tds', 'qid', 'od', 'hs', 'sos', 'prn', 'before food', 'after food',
        'morning', 'noon', 'evening', 'night', 'alternate day', 'weekly'
    ]
    number_pattern = r'\b\d+(\.\d+)?\b'

    for line in lines:
        line = line.strip()
        line_lower = line.lower()
        if not line:
            continue

        if is_likely_phone_number(line):
            continue

        name_pattern = r'^[A-Z][a-zA-Z0-9\s\-\.!]+$'
        if re.match(name_pattern, line) and not any(freq in line_lower for freq in frequency_keywords):
            current_medicine_name = re.sub(r'[!@#\$%\^&\*\(\)]', '', line).strip()
            for unit in dosage_keywords:
                if current_medicine_name.lower().endswith(f" {unit}"):
                    current_medicine_name = re.sub(fr'\s*\d+(\.\d+)?\s*{unit}\b', '', current_medicine_name, flags=re.IGNORECASE).strip()
                    break
            continue

        dosage = "Not specified"
        frequency = "Not specified"

        dosage_match = re.search(
            fr'({number_pattern})\s*({"|".join(dosage_keywords)})\b|\b({"|".join(dosage_keywords)})\s*({number_pattern})',
            line_lower, re.IGNORECASE
        )
        if dosage_match:
            if dosage_match.group(1) and dosage_match.group(2):
                dosage = f"{dosage_match.group(1)} {dosage_match.group(2)}"
            elif dosage_match.group(3) and dosage_match.group(4):
                dosage = f"{dosage_match.group(4)} {dosage_match.group(3)}"
        else:
            num_only_match = re.search(fr'({number_pattern})\s*(tablet|cap)?', line_lower)
            if num_only_match and (current_medicine_name or 'tablet' in line_lower or 'cap' in line_lower):
                dosage = num_only_match.group(1)
                if 'tablet' in line_lower:
                    dosage += " tablet(s)"
                elif 'cap' in line_lower:
                    dosage += " capsule(s)"

        xyz_match = re.search(r'\b(\d+)\s*-\s*(\d+)\s*-\s*(\d+)\b', line_lower)
        if xyz_match:
            frequency = f"Morning: {xyz_match.group(1)}, Afternoon: {xyz_match.group(2)}, Night: {xyz_match.group(3)}"
        else:
            for kw in frequency_keywords:
                freq_num_match = re.search(fr'({number_pattern})\s*({kw}|times\s*(a)?\s*day)', line_lower, re.IGNORECASE)
                if freq_num_match and "times" in freq_num_match.group(2):
                    frequency = f"{freq_num_match.group(1)} {freq_num_match.group(2)}"
                elif kw in line_lower:
                    frequency = kw
                    break

        if current_medicine_name:
            medicines.append({
                "name": current_medicine_name.strip(),
                "dosage": dosage.strip(),
                "frequency": frequency.strip()
            })
            current_medicine_name = None

    if not medicines and text.strip():
        return [{"name": "Could not parse medicine details", "dosage": "", "frequency": ""}]
    return medicines

def main():
    st.title("Handwritten Prescription Extractor")
    st.write("Upload a prescription image to extract medicine details.")

    # File uploader
    uploaded_file = st.file_uploader("Choose a prescription image", type=["png", "jpg", "jpeg"])

    if uploaded_file is not None:
        # Display uploaded image
        image = Image.open(uploaded_file)
        st.image(image, caption="Uploaded Prescription", width=400)

        if st.button("Extract Medicine Details"):
            with st.spinner("Processing..."):
                # Log processing steps
                log_placeholder = st.empty()
                log_lines = []

                def update_log(message):
                    log_lines.append(message)
                    log_placeholder.text("\n".join(log_lines))

                # Preprocess image
                update_log("1. Preprocessing image...")
                try:
                    processed_image = preprocess_image_for_ocr(image)
                    update_log("   Preprocessing complete.")
                except Exception as e:
                    update_log(f"   Error preprocessing: {e}")
                    st.error("Error during preprocessing.")
                    return

                # OCR
                update_log("2. Performing OCR...")
                detected_text, ocr_error = extract_text_from_image(processed_image, lang='eng')
                if ocr_error:
                    update_log(f"   OCR Error: {ocr_error}")
                    st.error("OCR failed.")
                    return
                if not detected_text:
                    update_log("   No text detected by OCR.")
                    st.error("No text detected by OCR.")
                    return

                update_log(f"   Raw OCR Text (first 200 chars): {detected_text[:200]}...")
                
                # Language detection and translation
                update_log("3. Detecting language and translating...")
                try:
                    source_lang = detect(detected_text) if detected_text.strip() else 'auto'
                    update_log(f"   Detected language: {source_lang}")
                    translated_text = translate_text_to_english(detected_text, source_lang)
                    update_log(f"   Translated Text (first 200 chars): {translated_text[:200]}...")
                except Exception as e:
                    update_log(f"   Language detection/translation failed: {e}. Using original text.")
                    translated_text = detected_text

                # Parse medicine details
                update_log("4. Parsing medicine details...")
                medicine_details = parse_medicine_details(translated_text)
                update_log("   Extracted details:")
                for med in medicine_details:
                    update_log(f"   - Name: {med['name']}")
                    update_log(f"     Dosage: {med['dosage']}")
                    update_log(f"     Frequency: {med['frequency']}")

                # Save to files
                update_log("5. Saving to files...")
                try:
                    # Medicine details file
                    medicine_filename = f"medicine_details_{uuid.uuid4().hex}.txt"
                    medicine_content = "Medicine Details:\n" + "="*30 + "\n"
                    for med in medicine_details:
                        medicine_content += f"Medicine Name: {med['name']}\n"
                        medicine_content += f"Dosage: {med['dosage']}\n"
                        medicine_content += f"Frequency: {med['frequency']}\n"
                        medicine_content += "-"*20 + "\n"
                    with open(medicine_filename, "w", encoding="utf-8") as f:
                        f.write(medicine_content)
                    update_log(f"   Saved medicine details to {medicine_filename}")

                    # Full details file
                    full_filename = f"prescription_full_details_{uuid.uuid4().hex}.txt"
                    full_content = "Translated Text:\n" + "="*30 + "\n" + translated_text
                    full_content += "\n\nRaw OCR Text:\n" + "="*30 + "\n" + detected_text
                    with open(full_filename, "w", encoding="utf-8") as f:
                        f.write(full_content)
                    update_log(f"   Saved full details to {full_filename}")

                    # Provide download buttons
                    with open(medicine_filename, "rb") as f:
                        st.download_button(
                            label="Download Medicine Details",
                            data=f,
                            file_name=medicine_filename,
                            mime="text/plain"
                        )
                    with open(full_filename, "rb") as f:
                        st.download_button(
                            label="Download Full Details",
                            data=f,
                            file_name=full_filename,
                            mime="text/plain"
                        )

                    st.success(f"Processing complete! Saved to {medicine_filename} and {full_filename}")
                    logging.info(f"Medicine details saved to {medicine_filename}")
                    logging.info(f"Full details saved to {full_filename}")
                except Exception as e:
                    update_log(f"   Error saving files: {e}")
                    st.error("Error saving files.")
                    logging.error(f"Error saving files: {e}")

if __name__ == "__main__":
    main()
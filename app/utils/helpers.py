import qrcode
import os
import uuid
from flask import current_app

def generate_qr(data, user_id):
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    
    # Ensure directory exists
    static_path = os.path.join(current_app.root_path, 'static', 'qrcodes')
    if not os.path.exists(static_path):
        os.makedirs(static_path)
        
    filename = f"user_{user_id}_{uuid.uuid4().hex[:8]}.png"
    file_path = os.path.join(static_path, filename)
    img.save(file_path)
    
    return f"qrcodes/{filename}"

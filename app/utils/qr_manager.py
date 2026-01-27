import uuid
import qrcode
import os
from PIL import Image, ImageDraw, ImageFont
from app.extensions import db
from app.models import TeamQR, Team, TeamMealUsage
from flask import current_app

def generate_team_qrs(team_id):
    """
    Generates ACCESS and DINNER QR codes for a team.
    Creates database records and saves image files.
    """
    team = Team.query.get(team_id)
    if not team:
        return False

    qr_types = ['ACCESS']
    
    if team.hackathon.enable_breakfast:
        qr_types.append('BREAKFAST')
    if team.hackathon.enable_lunch:
        qr_types.append('LUNCH')
    if team.hackathon.enable_dinner:
        qr_types.append('DINNER')

    generated_files = {}

    for q_type in qr_types:
        # 1. Check if exists
        existing_qr = TeamQR.query.filter_by(team_id=team_id, qr_type=q_type).first()
        if existing_qr:
            token = existing_qr.qr_token
        else:
            # 2. Generate Token
            token = str(uuid.uuid4())
            new_qr = TeamQR(team_id=team_id, qr_token=token, qr_type=q_type)
            db.session.add(new_qr)
        
        # 3. Generate Image
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(token) # ONLY token in QR data
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")
        
        # 4. Add Visual Text
        # Convert to RGB to add text
        img = img.convert('RGB')
        
        # Add a whitespace buffer at the bottom for text
        width, height = img.size
        # Estimate text height
        text_height = 60
        new_height = height + text_height
        
        new_img = Image.new('RGB', (width, new_height), 'white')
        new_img.paste(img, (0, 0))
        
        draw = ImageDraw.Draw(new_img)
        
        # Simple default font
        try:
            font = ImageFont.truetype("arial.ttf", 16)
        except IOError:
            font = ImageFont.load_default()

        # Text 1: Team Name
        draw.text((10, height + 5), f"Team: {team.name}", fill="black", font=font)
        # Text 2: Type
        draw.text((10, height + 25), f"Type: {q_type}", fill="red" if q_type=='DINNER' else "blue", font=font)
        
        # 5. Save File
        filename = f"team_{team_id}_{q_type}_{token[:8]}.png"
        save_dir = os.path.join(current_app.root_path, 'static', 'qrcodes', 'teams')
        os.makedirs(save_dir, exist_ok=True)
        
        file_path = os.path.join(save_dir, filename)
        new_img.save(file_path)
        
        generated_files[q_type] = f"qrcodes/teams/{filename}"

    db.session.commit()
    return generated_files

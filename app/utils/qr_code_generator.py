"""
QR Code generation and rendering utilities.
Converts QR tokens into scannable QR codes (images).
"""

import io
import base64
import qrcode
from typing import Tuple


class QRCodeGenerator:
    """Generate QR codes from tokens."""

    # QR Code settings
    QR_VERSION = 1  # Auto-adjust (None = auto)
    QR_ERROR_CORRECTION = qrcode.constants.ERROR_CORRECT_M  # ~15% recovery
    QR_BOX_SIZE = 10  # Pixels per box
    QR_BORDER = 2  # Border boxes

    @staticmethod
    def generate_qr_image(
        token: str,
        meal_type: str,
        team_member_name: str,
    ) -> bytes:
        """
        Generate a QR code image (PNG bytes) with embedded metadata.

        Args:
            token: QR token string
            meal_type: Meal type (BREAKFAST, LUNCH, DINNER)
            team_member_name: Name of the team member

        Returns:
            PNG image bytes
        """
        # Create QR data: format for easy parsing
        qr_data = f"MEAL|{meal_type}|{token}|{team_member_name}"

        qr = qrcode.QRCode(
            version=QRCodeGenerator.QR_VERSION,
            error_correction=QRCodeGenerator.QR_ERROR_CORRECTION,
            box_size=QRCodeGenerator.QR_BOX_SIZE,
            border=QRCodeGenerator.QR_BORDER,
        )
        qr.add_data(qr_data)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")

        # Return as PNG bytes
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="PNG")
        return img_bytes.getvalue()

    @staticmethod
    def generate_qr_base64(
        token: str,
        meal_type: str,
        team_member_name: str,
    ) -> str:
        """
        Generate a base64-encoded QR code for embedding in HTML/JSON.

        Args:
            token: QR token string
            meal_type: Meal type
            team_member_name: Name of the team member

        Returns:
            Base64-encoded PNG string (data URI compatible)
        """
        img_bytes = QRCodeGenerator.generate_qr_image(token, meal_type, team_member_name)
        return base64.b64encode(img_bytes).decode("utf-8")

    @staticmethod
    def generate_qr_data_uri(
        token: str,
        meal_type: str,
        team_member_name: str,
    ) -> str:
        """
        Generate a data URI for direct use in HTML img src.

        Args:
            token: QR token string
            meal_type: Meal type
            team_member_name: Name of the team member

        Returns:
            Data URI string (e.g., "data:image/png;base64,...")
        """
        b64 = QRCodeGenerator.generate_qr_base64(token, meal_type, team_member_name)
        return f"data:image/png;base64,{b64}"

    @staticmethod
    def parse_qr_data(qr_data: str) -> dict:
        """
        Parse QR code data back into components.
        Format: "MEAL|meal_type|token|name"

        Args:
            qr_data: QR data string

        Returns:
            {
                'meal_type': str,
                'token': str,
                'team_member_name': str,
            }
        """
        parts = qr_data.split("|")
        if len(parts) < 4 or parts[0] != "MEAL":
            raise ValueError("Invalid QR data format")

        return {
            "meal_type": parts[1],
            "token": parts[2],
            "team_member_name": parts[3],
        }

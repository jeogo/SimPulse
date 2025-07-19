"""
PDF Generator Utility
Generates settlement reports in Arabic
"""

import logging
import os
from datetime import datetime
from typing import Dict
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from bidi.algorithm import get_display
import arabic_reshaper
import urllib.request

logger = logging.getLogger(__name__)

class PDFGenerator:
    """PDF generator for settlement reports"""
    
    def __init__(self):
        # Get the project root directory (SimPulse folder)
        self.project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.output_dir = os.path.join(self.project_root, "data", "settlement_reports")
        self.fonts_dir = os.path.join(self.project_root, "data", "fonts")
        self.ensure_output_directory()
        self.ensure_fonts_directory()
        self.setup_arabic_font()
    
    def ensure_output_directory(self):
        """Create output directory if it doesn't exist"""
        try:
            os.makedirs(self.output_dir, exist_ok=True)
        except Exception as e:
            logger.error(f"Error creating output directory: {e}")
    
    def ensure_fonts_directory(self):
        """Create fonts directory if it doesn't exist"""
        try:
            os.makedirs(self.fonts_dir, exist_ok=True)
        except Exception as e:
            logger.error(f"Error creating fonts directory: {e}")
    
    def download_arabic_font(self):
        """Download a good Arabic font for PDF"""
        try:
            font_path = os.path.join(self.fonts_dir, "NotoSansArabic-Regular.ttf")
            
            if os.path.exists(font_path):
                logger.info("Arabic font already exists")
                return font_path
            
            logger.info("Arabic font not found, using system fallback")
            return None
        except Exception as e:
            logger.error(f"Error checking Arabic font: {e}")
            return None
    
    def setup_arabic_font(self):
        """Setup Arabic font for PDF generation"""
        try:
            # Multiple possible font paths
            font_paths = [
                os.path.join(self.fonts_dir, "NotoSansArabic-Regular.ttf"),
                os.path.join(os.getcwd(), "data", "fonts", "NotoSansArabic-Regular.ttf"),
                os.path.join(os.path.dirname(__file__), "..", "..", "data", "fonts", "NotoSansArabic-Regular.ttf")
            ]
            
            font_found = False
            for font_path in font_paths:
                font_path = os.path.abspath(font_path)
                if os.path.exists(font_path):
                    try:
                        pdfmetrics.registerFont(TTFont('ArabicFont', font_path))
                        self.arabic_font = 'ArabicFont'
                        logger.info(f"Arabic font registered successfully from: {font_path}")
                        font_found = True
                        break
                    except Exception as reg_error:
                        logger.warning(f"Could not register font from {font_path}: {reg_error}")
                        continue
            
            if not font_found:
                # List available paths for debugging
                logger.warning("Arabic font not found in any of these paths:")
                for path in font_paths:
                    abs_path = os.path.abspath(path)
                    exists = "EXISTS" if os.path.exists(abs_path) else "NOT FOUND"
                    logger.warning(f"  - {abs_path} [{exists}]")
                
                # Fallback to system fonts
                self.arabic_font = 'Helvetica'
                logger.warning("Using Helvetica fallback")
                
        except Exception as e:
            logger.error(f"Could not setup Arabic font: {e}")
            self.arabic_font = 'Helvetica'
    
    def format_arabic_text(self, text: str) -> str:
        """Format Arabic text for PDF display"""
        try:
            if not text:
                return ""
            
            # Reshape Arabic text
            reshaped_text = arabic_reshaper.reshape(str(text))
            # Apply bidirectional algorithm
            bidi_text = get_display(reshaped_text)
            
            return bidi_text
        except Exception as e:
            logger.warning(f"Error formatting Arabic text '{text}': {e}")
            return str(text)
    
    def format_currency(self, amount: float) -> str:
        """Format currency amount"""
        return f"{amount:,.2f} ر.س"
    
    def format_date(self, date_str: str) -> str:
        """Format date for display"""
        try:
            if isinstance(date_str, str):
                date_obj = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            else:
                date_obj = date_str
            
            return date_obj.strftime("%Y/%m/%d - %H:%M")
        except Exception as e:
            logger.warning(f"Error formatting date '{date_str}': {e}")
            return str(date_str)
    
    async def generate_settlement_report(self, settlement_data: Dict) -> Dict:
        """Generate settlement report PDF"""
        try:
            # Extract data
            user_data = settlement_data['user_data']
            sim_info = settlement_data.get('sim_info', {})
            verifications = settlement_data['verifications']
            
            # Generate filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            username = user_data.get('full_name', 'user').replace(' ', '_')
            filename = f"settlement_{user_data['telegram_id']}_{username}_{timestamp}.pdf"
            file_path = os.path.join(self.output_dir, filename)
            
            # Create PDF document
            doc = SimpleDocTemplate(
                file_path,
                pagesize=A4,
                rightMargin=50,
                leftMargin=50,
                topMargin=50,
                bottomMargin=50
            )
            
            # Build content
            story = []
            styles = getSampleStyleSheet()
            
            # Create custom styles for Arabic with improved font
            arabic_style = ParagraphStyle(
                'Arabic',
                parent=styles['Normal'],
                fontName=self.arabic_font,
                fontSize=14,
                alignment=2,  # Right alignment for Arabic
                spaceAfter=12,
                leading=20
            )
            
            title_style = ParagraphStyle(
                'ArabicTitle',
                parent=styles['Title'],
                fontName=self.arabic_font,
                fontSize=20,
                alignment=1,  # Center alignment
                spaceAfter=20,
                leading=24,
                textColor=colors.darkblue
            )
            
            header_style = ParagraphStyle(
                'ArabicHeader',
                parent=styles['Heading2'],
                fontName=self.arabic_font,
                fontSize=16,
                alignment=2,  # Right alignment
                spaceAfter=15,
                leading=20,
                textColor=colors.darkgreen
            )
            
            # Title
            title = self.format_arabic_text("تقرير التسوية المالية - نظام SimPulse")
            story.append(Paragraph(title, title_style))
            story.append(Spacer(1, 20))
            
            # Date header
            date_text = self.format_arabic_text(f"تاريخ التقرير: {self.format_date(datetime.now())}")
            story.append(Paragraph(date_text, arabic_style))
            story.append(Spacer(1, 20))
            
            # User Information Section
            user_info_title = self.format_arabic_text("معلومات المستخدم")
            story.append(Paragraph(user_info_title, header_style))
            
            user_info_data = [
                [self.format_arabic_text("الاسم الكامل"), self.format_arabic_text(user_data.get('full_name', 'غير محدد'))],
                [self.format_arabic_text("رقم الهاتف"), user_data.get('phone_number', 'غير محدد')],
                [self.format_arabic_text("معرف التليجرام"), str(user_data.get('telegram_id', 'غير محدد'))],
                [self.format_arabic_text("رقم الشريحة"), sim_info.get('phone_number', 'غير محدد')],
                [self.format_arabic_text("حالة المستخدم"), self.format_arabic_text("معتمد")],
            ]
            
            user_table = Table(user_info_data, colWidths=[2.5*inch, 3*inch])
            user_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (0, -1), colors.lightblue),
                ('TEXTCOLOR', (0, 0), (0, -1), colors.black),
                ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
                ('FONTNAME', (0, 0), (-1, -1), self.arabic_font),
                ('FONTSIZE', (0, 0), (-1, -1), 12),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
                ('TOPPADDING', (0, 0), (-1, -1), 12),
                ('BACKGROUND', (1, 0), (1, -1), colors.white),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ]))
            
            story.append(user_table)
            story.append(Spacer(1, 25))
            
            # Settlement Summary
            summary_title = self.format_arabic_text("ملخص التسوية")
            story.append(Paragraph(summary_title, header_style))
            
            summary_data = [
                [self.format_arabic_text("فترة التسوية"), 
                 f"{self.format_date(settlement_data['period_start'])} - {self.format_date(settlement_data['period_end'])}"],
                [self.format_arabic_text("عدد التحققات الناجحة"), str(settlement_data['total_verifications'])],
                [self.format_arabic_text("إجمالي المبلغ"), self.format_currency(settlement_data['total_amount'])],
                [self.format_arabic_text("تاريخ التسوية"), self.format_date(datetime.now())],
                [self.format_arabic_text("حالة التسوية"), self.format_arabic_text("مكتملة")],
            ]
            
            summary_table = Table(summary_data, colWidths=[2.5*inch, 3*inch])
            summary_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (0, -1), colors.lightgreen),
                ('TEXTCOLOR', (0, 0), (0, -1), colors.black),
                ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
                ('FONTNAME', (0, 0), (-1, -1), self.arabic_font),
                ('FONTSIZE', (0, 0), (-1, -1), 12),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
                ('TOPPADDING', (0, 0), (-1, -1), 12),
                ('BACKGROUND', (1, 0), (1, -1), colors.white),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ]))
            
            story.append(summary_table)
            story.append(Spacer(1, 25))
            
            # Verification Details
            if verifications:
                verif_title = self.format_arabic_text("تفاصيل التحققات")
                story.append(Paragraph(verif_title, header_style))
                
                # Table headers
                verif_headers = [
                    self.format_arabic_text("التاريخ والوقت"),
                    self.format_arabic_text("المبلغ (دج)"),
                    self.format_arabic_text("الحالة"),
                    self.format_arabic_text("تفاصيل إضافية")
                ]
                
                verif_data = [verif_headers]
                
                for verification in verifications:
                    row = [
                        self.format_date(verification['created_at']),
                        f"{float(verification['amount']):.2f}",
                        self.format_arabic_text("نجح" if verification['result'] == 'success' else "فشل"),
                        self.format_arabic_text(verification.get('details', ''))[:30] + "..." if len(verification.get('details', '')) > 30 else self.format_arabic_text(verification.get('details', ''))
                    ]
                    verif_data.append(row)
                
                verif_table = Table(verif_data, colWidths=[1.8*inch, 1*inch, 1*inch, 2.2*inch])
                verif_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                    ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                    ('FONTNAME', (0, 0), (-1, -1), self.arabic_font),
                    ('FONTSIZE', (0, 0), (-1, -1), 10),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                    ('TOPPADDING', (0, 0), (-1, -1), 8),
                    ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                    ('GRID', (0, 0), (-1, -1), 1, colors.black),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ]))
                
                story.append(verif_table)
            
            # Footer
            story.append(Spacer(1, 30))
            footer_text = self.format_arabic_text("تم إنتاج هذا التقرير تلقائياً بواسطة نظام SimPulse للتحقق من الرصيد")
            footer_style = ParagraphStyle(
                'Footer',
                parent=styles['Normal'],
                fontName=self.arabic_font,
                fontSize=10,
                alignment=1,
                textColor=colors.grey
            )
            story.append(Paragraph(footer_text, footer_style))
            
            # Build PDF
            doc.build(story)
            
            return {
                'success': True,
                'file_path': file_path,
                'filename': filename,
                'message': 'تم إنتاج التقرير بنجاح'
            }
            
        except Exception as e:
            logger.error(f"Error generating PDF report: {e}")
            return {
                'success': False,
                'message': f'خطأ في إنتاج التقرير: {str(e)}'
            }
    
    def cleanup_old_reports(self, days_to_keep: int = 30):
        """Clean up old settlement reports"""
        try:
            if not os.path.exists(self.output_dir):
                return
            
            current_time = datetime.now()
            cutoff_time = current_time.timestamp() - (days_to_keep * 24 * 60 * 60)
            
            for filename in os.listdir(self.output_dir):
                file_path = os.path.join(self.output_dir, filename)
                if os.path.isfile(file_path):
                    file_time = os.path.getmtime(file_path)
                    if file_time < cutoff_time:
                        os.remove(file_path)
                        logger.info(f"Removed old report: {filename}")
                        
        except Exception as e:
            logger.error(f"Error cleaning up old reports: {e}")

    def generate_settlement_report_sync(self, user_data: Dict, verifications: list, settlement_data: Dict, admin_data: Dict = None, group_data: Dict = None, sim_data: Dict = None) -> str:
        """Generate simple settlement report PDF (synchronous version)"""
        try:
            # Generate filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            username = user_data.get('full_name', 'user').replace(' ', '_')
            settlement_id = settlement_data.get('id', 'unknown')
            filename = f"settlement_{settlement_id}_{user_data['telegram_id']}_{username}_{timestamp}.pdf"
            file_path = os.path.join(self.output_dir, filename)
            
            # Create PDF document
            doc = SimpleDocTemplate(
                file_path,
                pagesize=A4,
                rightMargin=30,
                leftMargin=30,
                topMargin=30,
                bottomMargin=30
            )
            
            # Build content
            story = []
            styles = getSampleStyleSheet()
            
            # Simple styles with proper font usage
            normal_style = ParagraphStyle(
                'Normal',
                parent=styles['Normal'],
                fontName='Helvetica',  # Use Helvetica for English text
                fontSize=11,
                leading=16,
                alignment=0  # Left alignment
            )
            
            heading_style = ParagraphStyle(
                'Heading',
                parent=styles['Heading2'],
                fontName='Helvetica-Bold',  # Use Helvetica Bold for headings
                fontSize=14,
                leading=18,
                alignment=0,  # Left alignment
                spaceAfter=10
            )
            
            title_style = ParagraphStyle(
                'Title',
                parent=styles['Title'],
                fontName='Helvetica-Bold',  # Use Helvetica Bold for title
                fontSize=16,
                leading=20,
                alignment=1,  # Center alignment
                spaceAfter=20
            )
            
            # Simple title without Arabic reshaping
            story.append(Paragraph("Settlement Report", title_style))
            story.append(Spacer(1, 20))
            
            # User Information - Clean format
            story.append(Paragraph("USER INFORMATION", heading_style))
            story.append(Spacer(1, 10))
            
            # Create user info table for better layout
            user_info_data = [
                ["Full Name:", user_data.get('full_name', 'Not specified')],
                ["Phone Number:", user_data.get('phone_number', 'Not specified')],
                ["Telegram ID:", str(user_data.get('telegram_id', 'Not specified'))],
                ["User Status:", user_data.get('status', 'unknown').upper()]
            ]
            
            user_table = Table(user_info_data, colWidths=[120, 300])
            user_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (0, -1), colors.lightblue),
                ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
                ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
                ('ALIGN', (1, 0), (1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                ('TOPPADDING', (0, 0), (-1, -1), 8),
                ('BACKGROUND', (1, 0), (1, -1), colors.white),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ]))
            
            story.append(user_table)
            story.append(Spacer(1, 15))
            
            # Settlement Information - Clean format
            settlement_date = settlement_data.get('settlement_date', '')[:16] if settlement_data.get('settlement_date') else 'Not specified'
            total_amount = settlement_data.get('total_amount', 0)
            
            story.append(Paragraph("SETTLEMENT INFORMATION", heading_style))
            story.append(Spacer(1, 10))
            
            settlement_info_data = [
                ["Settlement ID:", f"#{settlement_data.get('id', 'Not specified')}"],
                ["Settlement Date:", settlement_date],
                ["Total Amount:", f"{total_amount:.2f} DZD"],
                ["Total Verifications:", str(len(verifications))]
            ]
            
            settlement_table = Table(settlement_info_data, colWidths=[120, 300])
            settlement_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (0, -1), colors.lightgreen),
                ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
                ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
                ('ALIGN', (1, 0), (1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                ('TOPPADDING', (0, 0), (-1, -1), 8),
                ('BACKGROUND', (1, 0), (1, -1), colors.white),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ]))
            
            story.append(settlement_table)
            story.append(Spacer(1, 20))
            
            # Verifications table
            story.append(Paragraph("VERIFICATION DETAILS", heading_style))
            story.append(Spacer(1, 10))
            
            # Create simple table data
            table_data = []
            
            # Headers in English with clear formatting
            headers = ["DATE & TIME", "AMOUNT (DZD)", "RESULT", "NOTES"]
            table_data.append(headers)
            
            # Add verification data
            successful_count = 0
            failed_count = 0
            successful_amount = 0
            
            for verification in verifications:
                date_str = verification.get('created_at', '')[:16] if verification.get('created_at') else 'Not specified'
                amount = verification.get('amount', 0)
                result = verification.get('result', 'unknown')
                notes = verification.get('notes', 'No notes')
                
                # Count successful verifications
                if result == 'success':
                    successful_count += 1
                    successful_amount += float(amount)
                    result_display = "SUCCESS"
                else:
                    failed_count += 1
                    result_display = "FAILED"
                
                row = [
                    date_str,
                    f"{amount:.2f}",
                    result_display,
                    notes[:40] + "..." if len(notes) > 40 else notes
                ]
                table_data.append(row)
            
            # Create table with clear styling
            table = Table(table_data, colWidths=[110, 70, 70, 230])
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.darkblue),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTNAME', (1, 1), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, 0), 10),
                ('FONTSIZE', (1, 1), (-1, -1), 9),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('TOPPADDING', (0, 0), (-1, 0), 12),
                ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
                ('TOPPADDING', (0, 1), (-1, -1), 8),
                ('BACKGROUND', (0, 1), (-1, -1), colors.white),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey]),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ]))
            
            story.append(table)
            story.append(Spacer(1, 20))
            
            # Summary of successful verifications
            story.append(Paragraph("SUMMARY", heading_style))
            story.append(Spacer(1, 10))
            
            success_rate = (successful_count / len(verifications) * 100) if len(verifications) > 0 else 0.0
            
            # Create summary table for better presentation
            summary_data = [
                ["Total Verifications:", str(len(verifications))],
                ["Successful Verifications:", str(successful_count)],
                ["Failed Verifications:", str(failed_count)],
                ["Total Successful Amount:", f"{successful_amount:.2f} DZD"],
                ["Success Rate:", f"{success_rate:.1f}%"],
                ["Settlement Date:", settlement_date],
                ["Report Generated:", datetime.now().strftime('%Y-%m-%d %H:%M:%S')]
            ]
            
            summary_table = Table(summary_data, colWidths=[160, 260])
            summary_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (0, -1), colors.lightyellow),
                ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
                ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
                ('ALIGN', (1, 0), (1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                ('TOPPADDING', (0, 0), (-1, -1), 8),
                ('BACKGROUND', (1, 0), (1, -1), colors.white),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ]))
            
            story.append(summary_table)
            
            # Build PDF
            doc.build(story)
            
            logger.info(f"Simple settlement report generated successfully: {file_path}")
            return file_path
            
        except Exception as e:
            logger.error(f"Error generating simple settlement report: {e}")
            return None
    
    def get_user_status_arabic(self, status: str) -> str:
        """Convert user status to Arabic"""
        status_map = {
            'approved': 'معتمد ✅',
            'pending': 'في الانتظار ⏳',
            'rejected': 'مرفوض ❌',
            'blocked': 'محظور 🚫'
        }
        return status_map.get(status, f'غير معروف ({status})')
    
    def get_sim_status_arabic(self, status: str) -> str:
        """Convert SIM status to Arabic"""
        status_map = {
            'active': 'نشطة ✅',
            'inactive': 'غير نشطة ❌',
            'maintenance': 'تحت الصيانة 🔧',
            'blocked': 'محظورة 🚫'
        }
        return status_map.get(status, f'غير معروف ({status})')

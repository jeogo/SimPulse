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
        self.output_dir = "data/settlement_reports"
        self.fonts_dir = "data/fonts"
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
            # Check if Arabic font exists
            font_path = os.path.join(self.fonts_dir, "NotoSansArabic-Regular.ttf")
            
            if os.path.exists(font_path):
                pdfmetrics.registerFont(TTFont('ArabicFont', font_path))
                self.arabic_font = 'ArabicFont'
                logger.info(f"Arabic font registered successfully from: {font_path}")
            else:
                # Fallback to system fonts
                self.arabic_font = 'Helvetica'
                logger.warning(f"Arabic font not found at: {font_path}, using Helvetica fallback")
                
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

    def generate_settlement_report_sync(self, user_data: Dict, verifications: list, settlement_data: Dict) -> str:
        """Generate settlement report PDF (synchronous version)"""
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
                rightMargin=50,
                leftMargin=50,
                topMargin=50,
                bottomMargin=50
            )
            
            # Build content
            story = []
            styles = getSampleStyleSheet()
            
            # Create custom styles for Arabic text
            arabic_style = ParagraphStyle(
                'ArabicNormal',
                parent=styles['Normal'],
                fontName=self.arabic_font,
                fontSize=12,
                leading=18,
                alignment=2  # Right alignment for Arabic
            )
            
            arabic_title_style = ParagraphStyle(
                'ArabicTitle',
                parent=styles['Title'],
                fontName=self.arabic_font,
                fontSize=18,
                leading=24,
                alignment=1,  # Center alignment
                spaceAfter=20
            )
            
            arabic_heading_style = ParagraphStyle(
                'ArabicHeading',
                parent=styles['Heading2'],
                fontName=self.arabic_font,
                fontSize=14,
                leading=20,
                alignment=2,  # Right alignment
                spaceAfter=12
            )
            
            # Title
            title_text = self.format_arabic_text("تقرير التسوية")
            story.append(Paragraph(title_text, arabic_title_style))
            story.append(Spacer(1, 20))
            
            # Settlement info
            settlement_date = settlement_data.get('settlement_date', '')[:16] if settlement_data.get('settlement_date') else 'غير محدد'
            total_amount = settlement_data.get('total_amount', 0)
            total_verifications = settlement_data.get('total_verifications', len(verifications))
            
            info_text = f"""
            معرف التسوية: #{settlement_data.get('id', 'غير محدد')}
            تاريخ التسوية: {settlement_date}
            إجمالي المبلغ: {total_amount:.2f} دج
            عدد التحققات: {total_verifications}
            """
            
            formatted_info = self.format_arabic_text(info_text)
            story.append(Paragraph(formatted_info, arabic_style))
            story.append(Spacer(1, 20))
            
            # User information
            user_info_title = self.format_arabic_text("معلومات المستخدم")
            story.append(Paragraph(user_info_title, arabic_heading_style))
            
            user_info_text = f"""
            الاسم الكامل: {user_data.get('full_name', 'غير محدد')}
            رقم الهاتف: {user_data.get('phone_number', 'غير محدد')}
            معرف تيليجرام: {user_data.get('telegram_id', 'غير محدد')}
            """
            
            formatted_user_info = self.format_arabic_text(user_info_text)
            story.append(Paragraph(formatted_user_info, arabic_style))
            story.append(Spacer(1, 20))
            
            # Verifications table
            verifications_title = self.format_arabic_text("تفاصيل التحققات")
            story.append(Paragraph(verifications_title, arabic_heading_style))
            
            # Create table data
            table_data = []
            
            # Headers (in Arabic)
            headers = [
                self.format_arabic_text("التاريخ"),
                self.format_arabic_text("المبلغ (دج)"),
                self.format_arabic_text("النتيجة"),
                self.format_arabic_text("ملاحظات")
            ]
            table_data.append(headers)
            
            # Add verification data
            for verification in verifications:
                date_str = verification.get('created_at', '')[:16] if verification.get('created_at') else 'غير محدد'
                amount = verification.get('amount', 0)
                result = 'نجح' if verification.get('result') == 'success' else 'فشل'
                notes = verification.get('notes', 'لا توجد ملاحظات')
                
                row = [
                    self.format_arabic_text(date_str),
                    f"{amount:.2f}",
                    self.format_arabic_text(result),
                    self.format_arabic_text(notes)
                ]
                table_data.append(row)
            
            # Create table
            table = Table(table_data, colWidths=[120, 80, 80, 200])
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), self.arabic_font),
                ('FONTSIZE', (0, 0), (-1, 0), 10),
                ('FONTNAME', (0, 1), (-1, -1), self.arabic_font),
                ('FONTSIZE', (0, 1), (-1, -1), 9),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            
            story.append(table)
            story.append(Spacer(1, 20))
            
            # Summary
            summary_title = self.format_arabic_text("ملخص التسوية")
            story.append(Paragraph(summary_title, arabic_heading_style))
            
            summary_text = f"""
            إجمالي عدد التحققات: {len(verifications)}
            إجمالي المبلغ: {total_amount:.2f} دج
            تاريخ إنشاء التقرير: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            """
            
            formatted_summary = self.format_arabic_text(summary_text)
            story.append(Paragraph(formatted_summary, arabic_style))
            
            # Build PDF
            doc.build(story)
            
            logger.info(f"Settlement report generated successfully: {file_path}")
            return file_path
            
        except Exception as e:
            logger.error(f"Error generating settlement report: {e}")
            return None


            
        return Response(pdf_bytes, mimetype='application/pdf', 
                        headers={"Content-Disposition": f"attachment;filename=PIS_{secure_filename(product.model_name)}.pdf"})
                        
    except Exception as e:
        return f"Error generating PDF with Playwright: {str(e)}"
    
@app.route('/download_specsheet/<int:product_id>')
def download_specsheet(product_id):
    product = Product.query.get_or_404(product_id)
    
    # 1. Process ALL Images to Base64 (Main image + Additional images)
    all_images_b64 = []
    
    # Collect all image paths
    image_paths = []
    if product.image_path:
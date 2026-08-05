import re
from turkanime_api import bypass
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

try:
    html = bypass.fetch('/arama', data={'arama': 'one piece'})
    logging.info(f'HTML Length: {len(html)}')
    
    # Log some sample text for context
    sample_text = html[:5000]
    logging.info(f'Sample Text: {sample_text[:100]}...')  # Only log a small part for brevity
    
    # Regex search and log results
    regex1_results = re.findall(r'/anime/([^"\\'>]+)["\\'] [^>]*?title=["\\']([^"\\']+?) izle', html)[:20]
    logging.info(f'Regex 1 Results: {regex1_results}')
    
    regex2_results = re.findall(r'/anime/([^"\\'>]+)', html)[:20]
    logging.info(f'Regex 2 Results: {regex2_results}')
    
except Exception as e:
    logging.error(f'Error fetching or processing HTML: {e}')
import requests
from bs4 import BeautifulSoup
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

urls = ['https://animecix.tv', 'https://ecchicix.com']
for url in urls:
    try:
        r = requests.get(url, timeout=20, headers={'User-Agent':'Mozilla/5.0'})
        logging.info(f'Status: {r.status_code}, Final URL: {r.url}')
        
        # Parse the HTML content
        soup = BeautifulSoup(r.text, 'html.parser')
        
        # Extract and log specific information
        title = soup.find('title').get_text()
        logging.info(f'Title: {title}')
        
        # Log some sample text for context
        sample_text = r.text[:4000]
        logging.info(f'Sample Text: {sample_text[:100]}...')  # Only log a small part for brevity
        
    except requests.exceptions.RequestException as e:
        logging.error(f'Error fetching {url}: {e}')
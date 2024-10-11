import requests
from bs4 import BeautifulSoup
import os
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# Set up logging
logging.basicConfig(filename='scrape_bashforever.log', level=logging.DEBUG,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# File path for the quotes
file_path = 'bashforever_quotes.txt'

# Create the file if it doesn't exist
if not os.path.exists(file_path):
    with open(file_path, 'w') as file:
        file.write('')

# Function to scrape a single quote page from bashforever.com
def scrape_quote(quote_id):
    url = f"https://bashforever.com/?{quote_id}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    logging.info(f"Fetching Quote #{quote_id} from {url}...")
    
    try:
        response = requests.get(url, headers=headers)
    except Exception as e:
        logging.error(f"Request failed for Quote #{quote_id}: {e}")
        return False
    
    # Check if the request was successful
    if response.status_code == 200:
        logging.debug(f"Successfully fetched content for Quote #{quote_id}.")
        soup = BeautifulSoup(response.content, 'html.parser')

        # Extract the quote text, vote count, and quote year
        try:
            quote_element = soup.find('div', class_='quotes')
            if quote_element:
                quote_id_tag = quote_element.find('a')
                vote_pos_tag = quote_element.find('span', class_='pos')  # Positive votes
                vote_neg_tag = quote_element.find('span', class_='neg')  # Negative votes
                
                # Determine the vote count based on which tag is available
                if vote_neg_tag:
                    vote_count = vote_neg_tag.text.strip()
                elif vote_pos_tag:
                    vote_count = vote_pos_tag.text.strip()
                else:
                    vote_count = "Unknown Votes"

                quote_text_tag = quote_element.find('div').next_sibling
                quote_year_tag = soup.find('div', class_='quoteYear')

                # Handle missing elements gracefully
                quote_id_text = quote_id_tag.text.strip() if quote_id_tag else "Unknown ID"
                quote_text = quote_text_tag.strip() if quote_text_tag else "No text available"
                quote_year = quote_year_tag.text.strip() if quote_year_tag else "Unknown Year"

                logging.info(f"Quote #{quote_id} - Text: {quote_text}, Votes: {vote_count}, Year: {quote_year}")
                
                # Write to the file
                with open(file_path, 'a') as file:
                    file.write(f"Quote #{quote_id}: {quote_text} (Votes: {vote_count}) (Year: {quote_year})\n")
                return True
            else:
                logging.warning(f"Quote #{quote_id} - Failed to find 'quotes' element.")
                return False
        except Exception as e:
            logging.warning(f"Quote #{quote_id} - Failed to extract content: {e}")
            return False
    elif response.status_code == 403:
        logging.warning(f"Quote #{quote_id} - Access forbidden (403).")
        return False
    else:
        logging.warning(f"Quote #{quote_id} - Page not found (status code: {response.status_code}).")
        return False

# Function to scrape a range of quotes concurrently
def scrape_all_quotes_concurrently(start_id, end_id, max_workers=10):
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(scrape_quote, quote_id): quote_id for quote_id in range(start_id, end_id + 1)}
        for future in as_completed(futures):
            quote_id = futures[future]
            try:
                success = future.result()
                if success:
                    logging.info(f"Successfully scraped Quote #{quote_id}.")
                else:
                    logging.warning(f"Failed to scrape Quote #{quote_id}.")
            except Exception as e:
                logging.error(f"Error scraping Quote #{quote_id}: {e}")

# Scrape quotes from 0 to 966506 using concurrent threads
scrape_all_quotes_concurrently(0, 966506, max_workers=20)

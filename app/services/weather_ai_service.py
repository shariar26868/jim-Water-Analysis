import os
import re
import logging
from datetime import datetime
from typing import Optional
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

class WeatherAIService:
    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            logger.warning("OPENAI_API_KEY not set. WeatherAIService will return None.")
            self.client = None
        else:
            self.client = AsyncOpenAI(api_key=self.api_key)

    async def estimate_wet_bulb_temp(self, location: str, date_str: Optional[str] = None) -> Optional[float]:
        if not self.client:
            return None
        
        if not location:
            logger.warning("No location provided for wet bulb temperature estimation.")
            return None

        if not date_str:
            date_str = datetime.now().strftime("%B %d, %Y")

        prompt = f"""
        Given the location '{location}' and the date '{date_str}', estimate the average or design wet bulb temperature in Fahrenheit for a cooling tower operation.
        Please respond with ONLY a single numeric float value and nothing else. No text, no symbols.
        Example: 78.5
        """
        
        try:
            logger.info(f"Estimating wet bulb temp for {location} on {date_str} via OpenAI...")
            response = await self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a meteorological data assistant. You only reply with single floating point numbers."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=10
            )
            
            result_text = response.choices[0].message.content.strip()
            
            match = re.search(r"[-+]?\d*\.\d+|\d+", result_text)
            if match:
                estimated_temp = float(match.group())
                logger.info(f"AI Estimated wet bulb temp: {estimated_temp}°F")
                return estimated_temp
            
            logger.warning(f"Could not parse numeric wet bulb temp from AI response: '{result_text}'")
            return None
        except Exception as e:
            logger.error(f"Failed to estimate wet bulb temp from AI: {e}")
            return None

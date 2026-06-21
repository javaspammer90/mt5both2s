import requests
import json
from datetime import datetime, timezone

class FundamentalEngine:
    """Modul untuk tarik dan parse kalender ekonomi (ForexFactory)."""
    
    def __init__(self):
        self.ff_url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }

    def fetch_this_week_events(self):
        """Ambil data JSON langsung dari ForexFactory API (unoficial)."""
        try:
            response = requests.get(self.ff_url, headers=self.headers, timeout=10)
            response.raise_for_status()
            events = response.json()
            return events
        except Exception as e:
            # print(f"[Fundamental] Error fetch: {e}")
            return []

    def get_high_impact_news(self, target_currencies=None):
        """Filter hanya berita High Impact."""
        events = self.fetch_this_week_events()
        high_impact = []
        
        # Format string tanggal sekarang (cek hari yang sama/mendatang)
        now = datetime.now(timezone.utc)

        for e in events:
            if e.get("impact") == "High":
                currency = e.get("country", "")
                
                # Filter mata uang jika ditentukan
                if target_currencies and currency not in target_currencies:
                    continue
                    
                high_impact.append(e)
                
        return high_impact

if __name__ == "__main__":
    engine = FundamentalEngine()
    print("--- HIGH IMPACT NEWS THIS WEEK ---")
    news = engine.get_high_impact_news(["USD", "EUR", "GBP", "JPY"])
    for n in news:
        print(f"[{n['date']}] {n['country']} - {n['title']} (Prev: {n.get('previous')}, Forecast: {n.get('forecast')})")

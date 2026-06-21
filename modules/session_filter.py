from datetime import datetime, timezone, time

def is_in_trading_session(utc_time: datetime) -> bool:
    """
    Check if the current UTC time falls within London & New York session crossover / active hours.
    Permitted hours: 07:00 to 22:00 UTC.
    """
    # Ensure timezone is UTC
    utc_dt = utc_time.astimezone(timezone.utc)
    t = utc_dt.time()
    
    start_time = time(7, 0, 0)
    end_time = time(22, 0, 0)
    
    return start_time <= t <= end_time

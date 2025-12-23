import httpx

from kmua.logger import logger


async def get_ip_info(url: str) -> dict | str:
    """Get IP/URL information from ip-api.com.

    Returns:
        dict: IP information if successful.
        str: Error message if the query fails.
    """
    logger.debug(f"get ip info for {url}")
    try:
        async with httpx.AsyncClient() as client:
            data = await client.get(
                url="http://ip-api.com/json/" + url,
                params={
                    "fields": "status,message,country,regionName,"
                    "city,lat,lon,isp,org,as,mobile,proxy,hosting,query"
                },
            )
        ipinfo_json = data.json()
        if ipinfo_json["status"] != "success":
            return f"Api query failed with message: {ipinfo_json['message']}"
        return {
            "query": ipinfo_json["query"],
            "country": ipinfo_json["country"],
            "region": ipinfo_json["regionName"],
            "city": ipinfo_json["city"],
            "lat": ipinfo_json["lat"],
            "lon": ipinfo_json["lon"],
            "isp": ipinfo_json["isp"],
            "org": ipinfo_json["org"],
            "as": ipinfo_json["as"],
            "mobile": ipinfo_json["mobile"],
            "proxy": ipinfo_json["proxy"],
            "hosting": ipinfo_json["hosting"],
        }
    except Exception as e:
        logger.error(f"Error fetching IP info: {e.__class__.__name__}: {e}")
        return f"Error fetching IP info: {e.__class__.__name__}"

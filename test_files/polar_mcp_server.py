import json
import os

import requests
from dotenv import load_dotenv
from mcp.server.mcpserver import MCPServer

load_dotenv()

# ================= KONFIGURACJA =================
# DANE APLIKACJI (KONEKTORA) Z PANELU POLAR - wartości w .env
CLIENT_ID = os.getenv("POLAR_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("POLAR_CLIENT_SECRET", "")

# TOKEN I ID Z auth_script.py
ACCESS_TOKEN = os.getenv("POLAR_ACCESS_TOKEN", "")
USER_ID = os.getenv("POLAR_USER_ID", "")

BASE_URL = "https://www.polaraccesslink.com"
HEADERS = {
    "Accept": "application/json",
    "Authorization": f"Bearer {ACCESS_TOKEN}"
}
# ================================================

# Inicjalizacja serwera MCP
mcp = MCPServer("Polar API Connector")


@mcp.tool()
def get_sleep_data() -> str:
    """
    Pobiera najnowsze dane o śnie użytkownika z Polar API (czas trwania, ocena snu, ciągłość).
    Używaj tego, gdy użytkownik pyta, jak spał, ile spał lub o jakość snu.
    """
    url = f"{BASE_URL}/v3/users/sleep"
    try:
        response = requests.get(url, headers=HEADERS)
        if response.status_code == 200:
            data = response.json()
            sleeps = data.get("sleeps", [])
            if not sleeps:
                return "Brak zapisanych danych o śnie w ostatnim czasie."

            # Bierzemy najnowszy zapis
            latest = sleeps[0]
            date = latest.get("date")
            sleep_score = latest.get("sleep_score")
            duration_hours = round(latest.get("sleep_time", 0) / 3600, 1)  # Konwersja sekund na godziny

            return f"Dane o śnie z {date}: Czas snu to ok. {duration_hours}h. Wynik snu (Sleep Score): {sleep_score}/100."
        else:
            return f"Błąd podczas pobierania danych o śnie: {response.status_code}"
    except Exception as e:
        return f"Błąd połączenia: {str(e)}"


@mcp.tool()
def get_nightly_recharge() -> str:
    """
    Pobiera status Nightly Recharge (regeneracja AUN - Autonomicznego Układu Nerwowego).
    Używaj tego, gdy użytkownik pyta o regenerację, status AUN, czy jest wypoczęty do treningu.
    """
    url = f"{BASE_URL}/v3/users/nightly-recharge"
    try:
        response = requests.get(url, headers=HEADERS)
        if response.status_code == 200:
            data = response.json()
            recharges = data.get("recharges", [])
            if not recharges:
                return "Brak najnowszych danych Nightly Recharge."

            latest = recharges[0]
            date = latest.get("date")
            status = latest.get("nightly_recharge_status")
            ans_charge = latest.get("ans_charge")

            return f"Status Nightly Recharge z {date}: Ogólna regeneracja: {status}. Wskaźnik AUN (Autonomicznego Układu Nerwowego): {ans_charge}."
        else:
            return f"Błąd podczas pobierania Nightly Recharge: {response.status_code}"
    except Exception as e:
        return f"Błąd połączenia: {str(e)}"


@mcp.tool()
def get_daily_activity() -> str:
    """
    Pobiera dane o dzisiejszej dziennej aktywności z Polar API, używając mechanizmu transakcji.
    Zwraca m.in. ilość kroków, spalone kalorie i status osiągnięcia celu.
    Używaj tego, gdy użytkownik pyta o dzisiejsze kroki, spalone kalorie lub czy dużo się ruszał.
    """
    transaction_url = f"{BASE_URL}/v3/users/{USER_ID}/activity-transactions"

    try:
        post_response = requests.post(transaction_url, headers=HEADERS)

        if post_response.status_code == 204:
            return "Brak nowych, niezsynchronizowanych danych o aktywności na serwerze Polar. Upewnij się, że zsynchronizowałeś zegarek z aplikacją Polar Flow w telefonie."

        elif post_response.status_code == 201:
            transaction_data = post_response.json()
            transaction_id = transaction_data.get("transaction-id")

            if not transaction_id:
                return "Utworzono transakcję, ale nie otrzymano jej ID."

            list_url = f"{BASE_URL}/v3/users/{USER_ID}/activity-transactions/{transaction_id}"
            list_response = requests.get(list_url, headers=HEADERS)

            if list_response.status_code == 200:
                activities = list_response.json().get("activity-log", [])
                if not activities:
                    requests.put(list_url, headers=HEADERS)
                    return "Transakcja otworzona, ale brak w niej podsumowań dni."

                activity_url = activities[0]
                details_response = requests.get(activity_url, headers=HEADERS)
                requests.put(list_url, headers=HEADERS)

                if details_response.status_code == 200:
                    details = details_response.json()
                    steps = details.get("active-steps", 0)
                    calories = details.get("calories", 0)
                    date = details.get("date")

                    return f"Dzienna aktywność z {date}: Zrobiłeś dziś {steps} kroków i spaliłeś {calories} kcal."
                else:
                    return f"Nie udało się pobrać szczegółów aktywności (kod {details_response.status_code})."
            else:
                requests.put(list_url, headers=HEADERS)
                return f"Błąd pobierania listy w transakcji (kod {list_response.status_code})."
        else:
            return f"Błąd podczas tworzenia transakcji (kod {post_response.status_code}). Treść: {post_response.text}"

    except Exception as e:
        return f"Błąd połączenia: {str(e)}"


if __name__ == "__main__":
    mcp.run()
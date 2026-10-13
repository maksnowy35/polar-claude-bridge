import base64
import os
from urllib.parse import urlparse, parse_qs

import requests
from dotenv import load_dotenv

load_dotenv()

# DANE APLIKACJI (KONEKTORA) Z PANELU POLAR - wartości w .env
CLIENT_ID = os.getenv("POLAR_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("POLAR_CLIENT_SECRET", "")


def authenticate_polar():
    # 1. Generowanie linku autoryzacyjnego
    auth_url = f"https://flow.polar.com/oauth2/authorization?response_type=code&client_id={CLIENT_ID}"

    print("=" * 60)
    print("1. Kliknij poniższy link (lub skopiuj i wklej go do przeglądarki):")
    print(auth_url)
    print("=" * 60)
    print("Zaloguj się na swoje konto Polar (tam gdzie masz dane z zegarka) i zaakceptuj uprawnienia.")
    print(
        "Po zaakceptowaniu przeglądarka 'zawiesi się' lub pokaże błąd wczytywania (np. stronę http://localhost/?code=...). To całkowicie poprawne!")

    # 2. Pobranie adresu zwrotnego od użytkownika
    redirected_url = input(
        "\n2. Wklej tutaj CAŁY ADRES URL z paska przeglądarki (ten na który Cię przekierowało): ").strip()

    # Wyciąganie kodu autoryzacyjnego z wklejonego adresu
    try:
        parsed_url = urlparse(redirected_url)
        auth_code = parse_qs(parsed_url.query)['code'][0]
        print(f"[+] Udało się wyciągnąć kod: {auth_code}")
    except Exception:
        print("[-] Błąd: Nie udało się odczytać kodu z podanego adresu. Upewnij się, że wkleiłeś cały URL z '?code='.")
        return

    # 3. Wymiana jednorazowego kodu na Access Token
    print("\n3. Wymieniam kod na Access Token...")
    token_url = "https://polarremote.com/v2/oauth2/token"

    # Polar wymaga autoryzacji "Basic", czyli zakodowania ID:SECRET w formacie Base64
    auth_string = f"{CLIENT_ID}:{CLIENT_SECRET}"
    auth_bytes = auth_string.encode('ascii')
    base64_bytes = base64.b64encode(auth_bytes)
    base64_string = base64_bytes.decode('ascii')

    headers = {
        "Authorization": f"Basic {base64_string}",
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json;charset=UTF-8"
    }
    data = {
        "grant_type": "authorization_code",
        "code": auth_code
    }

    response = requests.post(token_url, headers=headers, data=data)

    if response.status_code == 200:
        token_data = response.json()
        access_token = token_data.get("access_token")
        user_id = token_data.get("x_user_id")  # To jest Twoje prawdziwe USER_ID!

        print("\n✅ SUKCES! Zdobyliśmy token i ID.")
        print("-" * 50)
        print(f'ACCESS_TOKEN = "{access_token}"')
        print(f'USER_ID = "{user_id}"')
        print("-" * 50)

        # 4. Obowiązkowa rejestracja (Inicjalizacja udostępniania danych w Polar API)
        print("\n4. Rejestruję użytkownika (konieczne, by API włączyło przesyłanie Twoich danych)...")
        reg_url = "https://www.polaraccesslink.com/v3/users"
        reg_headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}"
        }
        reg_data = {"member-id": str(user_id)}

        reg_resp = requests.post(reg_url, headers=reg_headers, json=reg_data)
        if reg_resp.status_code in [200, 201]:
            print("✅ SUKCES: Użytkownik zarejestrowany. Twój kanał danych jest OTWARTY!")
        elif reg_resp.status_code == 409:
            print("✅ INFO: Użytkownik był już wcześniej zarejestrowany.")
        else:
            print(f"⚠️ UWAGA: Problem z rejestracją: {reg_resp.status_code} - {reg_resp.text}")

        print("\nGotowe! Skopiuj uzyskany wyżej ACCESS_TOKEN oraz USER_ID i wklej je do swojego Skryptu z Kroku 3.")
    else:
        print(f"\n❌ BŁĄD przy pobieraniu tokena ({response.status_code}): {response.text}")


if __name__ == "__main__":
    authenticate_polar()
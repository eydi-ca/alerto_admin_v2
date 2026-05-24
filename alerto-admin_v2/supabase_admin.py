import os
from datetime import datetime

from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if SUPABASE_URL:
    SUPABASE_URL = SUPABASE_URL.strip().rstrip("/")

    # Prevent accidental use of REST/Data API URL.
    if "/rest/v1" in SUPABASE_URL:
        SUPABASE_URL = SUPABASE_URL.split("/rest/v1")[0]

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise RuntimeError(
        "Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY in .env"
    )

print("Using Supabase URL:", SUPABASE_URL)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)


def _prefix_for_role(role: str) -> str:
    if role == "rescuer":
        return "R"
    if role == "admin":
        return "A"
    return "U"


def generate_user_code(role: str) -> str:
    """
    Generates compact user codes:
    resident -> U001
    rescuer  -> R001
    admin    -> A001
    """
    prefix = _prefix_for_role(role)

    result = (
        supabase
        .table("profiles")
        .select("user_code")
        .execute()
    )

    existing_codes = []

    for row in result.data or []:
        code = row.get("user_code")

        if not code:
            continue

        code = str(code).strip().upper()

        if code.startswith(prefix):
            number_part = code.replace(prefix, "", 1)

            try:
                existing_codes.append(int(number_part))
            except ValueError:
                pass

    next_number = max(existing_codes, default=0) + 1
    return f"{prefix}{next_number:03d}"


def internal_email_for_user_code(user_code: str) -> str:
    return f"{user_code.lower()}@alerto.local"


def create_auth_user(user_code: str, password: str, role: str):
    """
    Creates a Supabase Auth user using hidden internal email.
    Example:
    U001 -> u001@alerto.local
    """
    internal_email = internal_email_for_user_code(user_code)

    response = supabase.auth.admin.create_user({
        "email": internal_email,
        "password": password,
        "email_confirm": True,
        "user_metadata": {
            "user_code": user_code,
            "role": role,
        },
    })

    auth_user = getattr(response, "user", None)

    if auth_user is None:
        raise RuntimeError(f"Supabase Auth user creation failed: {response}")

    return auth_user


def create_resident_account(
    full_name: str,
    phone_number: str,
    address: str,
    password: str,
):
    user_code = generate_user_code("resident")
    auth_user = create_auth_user(
        user_code=user_code,
        password=password,
        role="resident",
    )

    profile_response = (
        supabase
        .table("profiles")
        .insert({
            "auth_user_id": auth_user.id,
            "user_code": user_code,
            "full_name": full_name,
            "phone_number": phone_number,
            "address": address,
            "role": "resident",
            "approval_status": "pending",
        })
        .execute()
    )

    if not profile_response.data:
        raise RuntimeError(f"Profile insert failed: {profile_response}")

    profile = profile_response.data[0]

    return {
        "user_code": user_code,
        "profile": profile,
        "approval_status": "pending",
    }


def create_rescuer_account(
    full_name: str,
    phone_number: str,
    address: str,
    password: str,
    organization: str,
    rescuer_id: str,
    assigned_zone: str,
    assigned_subzone: str,
):
    user_code = generate_user_code("rescuer")
    auth_user = create_auth_user(
        user_code=user_code,
        password=password,
        role="rescuer",
    )

    profile_response = (
        supabase
        .table("profiles")
        .insert({
            "auth_user_id": auth_user.id,
            "user_code": user_code,
            "full_name": full_name,
            "phone_number": phone_number,
            "address": address,
            "role": "rescuer",
            "approval_status": "approved",
        })
        .execute()
    )

    if not profile_response.data:
        raise RuntimeError(f"Profile insert failed: {profile_response}")

    profile = profile_response.data[0]

    rescuer_response = (
        supabase
        .table("rescuer_profiles")
        .insert({
            "profile_id": profile["id"],
            "organization": organization,
            "rescuer_id": rescuer_id,
            "assigned_zone": assigned_zone,
            "assigned_subzone": assigned_subzone,
            "verification_status": "approved",
        })
        .execute()
    )

    if not rescuer_response.data:
        raise RuntimeError(f"Rescuer profile insert failed: {rescuer_response}")

    rescuer_profile = rescuer_response.data[0]

    return {
        "user_code": user_code,
        "profile": profile,
        "rescuer_profile": rescuer_profile,
        "approval_status": "approved",
        "verification_status": "approved",
    }
    
def get_pending_residents():
    """
    Fetch resident profiles waiting for admin approval.
    """
    result = (
        supabase
        .table("profiles")
        .select("*")
        .eq("role", "resident")
        .eq("approval_status", "pending")
        .order("created_at", desc=True)
        .execute()
    )

    return result.data or []


def get_all_residents():
    """
    Fetch all resident profiles for admin review.
    """
    result = (
        supabase
        .table("profiles")
        .select("*")
        .eq("role", "resident")
        .order("created_at", desc=True)
        .execute()
    )

    return result.data or []


def update_resident_approval(profile_id: str, approval_status: str):
    """
    Approve, reject, or suspend a resident profile.
    """
    if approval_status not in ["approved", "rejected", "suspended", "pending"]:
        raise ValueError("Invalid approval status.")

    result = (
        supabase
        .table("profiles")
        .update({
            "approval_status": approval_status,
        })
        .eq("id", profile_id)
        .eq("role", "resident")
        .execute()
    )

    if not result.data:
        raise RuntimeError("No resident profile was updated.")

    return result.data[0]
  
def get_profile_by_user_code(user_code: str):
  result = (
      supabase
      .table("profiles")
      .select("*")
      .eq("user_code", user_code)
      .execute()
  )

  if not result.data:
      return None

  return result.data[0]

def reset_user_password(auth_user_id: str, new_password: str):
    """
    Reset a user's Supabase Auth password using the server-side service role key.
    This should only be called from the Flask admin/server.
    """
    if not new_password or len(new_password) < 6:
        raise ValueError("Password/PIN must be at least 6 characters.")

    response = supabase.auth.admin.update_user_by_id(
        auth_user_id,
        {
            "password": new_password,
        }
    )

    updated_user = getattr(response, "user", None)

    if updated_user is None:
        raise RuntimeError(f"Password reset failed: {response}")

    return updated_user
  
def update_resident_profile(
    profile_id: str,
    full_name: str,
    phone_number: str,
    address: str,
):
    """
    Update editable resident profile information.
    Does not allow changing user_code, role, auth_user_id, or approval_status here.
    """
    result = (
        supabase
        .table("profiles")
        .update({
            "full_name": full_name,
            "phone_number": phone_number,
            "address": address,
        })
        .eq("id", profile_id)
        .eq("role", "resident")
        .execute()
    )

    if not result.data:
        raise RuntimeError("No resident profile was updated.")

    return result.data[0]
  
def get_profiles_for_offline_sync():
    """
    Fetch approved profiles from Supabase so the Raspberry Pi can cache them locally.
    These records are used by the dashboard and receiver.py during offline operation.
    """
    result = (
        supabase
        .table("profiles")
        .select("*")
        .eq("approval_status", "approved")
        .order("created_at", desc=True)
        .execute()
    )

    return result.data or []


def get_devices_for_offline_sync():
    """
    Fetch approved device records from Supabase if the devices table exists.
    If the table is empty or unavailable, the dashboard can still use local configured stations.
    """
    try:
        result = (
            supabase
            .table("devices")
            .select("*")
            .eq("approval_status", "approved")
            .execute()
        )

        return result.data or []

    except Exception:
        return []


def get_stations_for_offline_sync():
    """
    Fetch station records from Supabase if the stations table exists.
    If not available, local Flask STATIONS config will be used as fallback.
    """
    try:
        result = (
            supabase
            .table("stations")
            .select("*")
            .execute()
        )

        return result.data or []

    except Exception:
        return []
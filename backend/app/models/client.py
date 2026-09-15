from typing import Optional, Dict, Any
from pydantic import BaseModel, Field

# ── Setup registry ─────────────────────────────────────────────────────────────

ALL_SETUPS = ["widget", "web_api", "whatsapp", "facebook", "telegram", "slack"]

SETUP_META = {
    "widget":   {"label": "Website Widget",      "emoji": "🌐", "always_available": True},
    "web_api":  {"label": "REST API",            "emoji": "⚡", "always_available": True},
    "whatsapp": {"label": "WhatsApp Business",   "emoji": "💬", "always_available": False},
    "facebook": {"label": "Facebook Messenger",  "emoji": "💙", "always_available": False},
    "telegram": {"label": "Telegram Bot",        "emoji": "✈️", "always_available": False},
    "slack":    {"label": "Slack Bot",           "emoji": "🟣", "always_available": False},
}


def setup_defaults(channel: str) -> dict:
    """Return the default config dict for a channel setup."""
    base: dict = {
        "enabled": channel in ("widget", "web_api"),
        "rate_limit_rpm": 20,
        "rate_limit_rpd": 200,
        "max_queries_per_session": 50,
        "context_mode": "none",              # "none" | "adaptive" | "full"
        "context_instructions": "",          # Specific entities/details to track
        "context_capacity": 4,               # Number of turns to scan
        "menu_tree": [],                     # Channel-specific or inherited menu tree
        "menu_graph_nodes": [],              # Serial-numbered dynamic menu graph nodes
        "menu_graph_root_node_id": "MENU_ROOT",
        "context_images": [],                # Contextual image triggers
        "descriptive_rules": [],             # Client-configured descriptive trigger policies
    }
    if channel == "widget":
        base.update({"allowed_origins": []})   # secured by Origin header, no token needed
    elif channel == "web_api":
        base.update({"token": ""})             # secured by API key (token), no Origin (server-side)
    elif channel == "whatsapp":
        base.update({
            "phone_number_id": "", "access_token": "",
            "app_secret": "", "verify_token": "",
        })
    elif channel == "facebook":
        base.update({
            "page_id": "", "page_access_token": "",
            "app_secret": "", "verify_token": "",
        })
    elif channel == "telegram":
        base.update({"bot_token": "", "secret_token": ""})
    elif channel == "slack":
        base.update({"bot_token": "", "signing_secret": ""})
    return base


def default_setups() -> dict:
    return {ch: setup_defaults(ch) for ch in ALL_SETUPS}


def get_setup(settings: dict, channel: str) -> dict:
    """
    Read a setup config from the settings dict, filling any missing keys
    with defaults. Works for both new (setups-based) and legacy documents.
    """
    setups = settings.get("setups") or {}
    cfg = dict(setups.get(channel, {}))

    # Fill missing keys from defaults
    defaults = setup_defaults(channel)
    for k, v in defaults.items():
        if k not in cfg:
            cfg[k] = v

    # Legacy migration: pull old top-level fields if setups not present
    if not setups:
        if channel == "widget":
            cfg["token"] = settings.get("widget_token", "")
            cfg["allowed_origins"] = settings.get("allowed_origins", [])
            cfg["rate_limit_rpm"] = settings.get("ip_rate_limit_rpm", 20)
            cfg["rate_limit_rpd"] = settings.get("ip_rate_limit_rpd", 200)
            cfg["max_queries_per_session"] = settings.get("max_queries_per_session", 50)
            cfg["enabled"] = True
        elif channel == "web_api":
            cfg["rate_limit_rpm"] = settings.get("ip_rate_limit_rpm", 20)
            cfg["rate_limit_rpd"] = settings.get("ip_rate_limit_rpd", 200)
            cfg["max_queries_per_session"] = settings.get("max_queries_per_session", 50)
            cfg["enabled"] = True
        elif channel == "whatsapp":
            old = settings.get("whatsapp_config") or {}
            cfg.update({k: old.get(k, "") for k in ("phone_number_id", "access_token", "app_secret", "verify_token")})
        elif channel == "facebook":
            old = settings.get("facebook_config") or {}
            cfg.update({k: old.get(k, "") for k in ("page_id", "page_access_token", "app_secret", "verify_token")})
        elif channel == "telegram":
            old = settings.get("telegram_config") or {}
            cfg.update({k: old.get(k, "") for k in ("bot_token", "secret_token")})
        elif channel == "slack":
            old = settings.get("slack_config") or {}
            cfg.update({k: old.get(k, "") for k in ("bot_token", "signing_secret")})

    return cfg


# ── Pydantic models ────────────────────────────────────────────────────────────

class SubMenu(BaseModel):
    id: str
    label: str
    sub_questions: list[str] = Field(default_factory=list)


class MenuOption(BaseModel):
    id: str
    label: str
    submenus: list[SubMenu] = Field(default_factory=list)


class MenuNode(BaseModel):
    id: str
    label: str
    description: Optional[str] = ""
    descriptor_tag: Optional[str] = ""    # Context condition when to trigger this menu stream
    frequency: str = "on_intent"          # "only_once" | "always" | "on_intent"
    action_question: Optional[str] = ""   # Leaf node: full question sent to RAG pipeline
    children: list["MenuNode"] = Field(default_factory=list)


class ContextImage(BaseModel):
    id: str
    title: str
    image_path: str                       # Path in repo public folder (e.g. /images/...) or URL
    descriptor_tag: str                   # Context condition when this image should be inserted
    caption: Optional[str] = ""
    frequency: str = "on_intent"          # "only_once" | "always" | "on_intent"


class DescriptiveRule(BaseModel):
    id: str
    title: str
    trigger_type: str = "on_intent"       # "first_turn" | "context_match" | "always" | "on_intent"
    prompt_directive: str                 # Inbuilt prompt instructions / context rule
    target_menu_id: Optional[str] = None  # Optional linked menu ID
    target_image_id: Optional[str] = None # Optional linked image ID


class ClientSettings(BaseModel):
    # Global chat behaviour
    welcome_message: str = "Hello! How can I help you today?"
    system_prompt: Optional[str] = None
    max_history_turns: int = 5
    theme_color: str = "#1E40AF"
    chatbot_title: str = "AI Front Desk"
    custom_widget_script: str = ""
    menu_options: list[MenuOption] = Field(default_factory=list)
    menu_tree: list[MenuNode] = Field(default_factory=list)
    menu_graph_nodes: list[Dict[str, Any]] = Field(default_factory=list)
    menu_graph_root_node_id: Optional[str] = "MENU_ROOT"
    context_images: list[ContextImage] = Field(default_factory=list)
    descriptive_rules: list[DescriptiveRule] = Field(default_factory=list)

    # Pre-compiled runtime snapshot (cached in MongoDB & in-memory)
    compiled_profile: Optional[Dict[str, Any]] = None

    # Context-Adaptive RAG settings
    context_mode: str = "none"              # "none" | "adaptive" | "full"
    context_instructions: str = ""
    context_capacity: int = 4

    # Per-setup configs (widget, web_api, whatsapp, facebook, telegram, slack)
    setups: Dict[str, Any] = Field(default_factory=default_setups)



class ClientCreate(BaseModel):
    client_id: str
    name: str
    domain: str = ""
    settings: ClientSettings = Field(default_factory=ClientSettings)
    admin_email: Optional[str] = None
    admin_password: Optional[str] = None



class ClientResponse(BaseModel):
    client_id: str
    name: str
    domain: str
    settings: ClientSettings

def route_intent(text: str) -> str:
    """
    Determine the high-level action requested by the user.

    Returns one of:
    - CREATE_ALERT_RULE
    - QUERY_STATUS
    - LIST_RULES
    - UNSUPPORTED
    """

    text_lower = text.lower().strip()

    # Requests that are clearly outside the monitoring system.
    unsupported_phrases = [
        "turn off",
        "turn on",
        "switch off",
        "switch on",
        "unlock",
        "lock the door",
        "open the gate",
        "close the gate",
        "start the machine",
        "stop the machine",
    ]

    if any(phrase in text_lower for phrase in unsupported_phrases):
        return "UNSUPPORTED"

    # Requests to inspect existing rules.
    list_rule_phrases = [
        "list rules",
        "show rules",
        "show me the rules",
        "existing rules",
        "monitoring rules",
        "alert rules",
    ]

    if any(phrase in text_lower for phrase in list_rule_phrases):
        return "LIST_RULES"

    # Requests asking for the current state/value of a device.
    query_phrases = [
        "what's",
        "what is",
        "how much",
        "right now",
        "currently",
        "current",
        "status",
    ]

    if any(phrase in text_lower for phrase in query_phrases):
        return "QUERY_STATUS"

    # Requests to create a monitoring/alert rule.
    alert_phrases = [
        "alert me",
        "alert",
        "notify me",
        "notify",
        "send me an alert",
        "if",
        "when",
        "stays above",
        "stays below",
        "exceeds",
        "falls below",
    ]

    if any(phrase in text_lower for phrase in alert_phrases):
        return "CREATE_ALERT_RULE"

    # Safest fallback when we don't understand the request.
    return "UNSUPPORTED"
"""
Page State Detector for ReachOps Autonomous Client
This module identifies and classifies the current page state during execution.
"""

import re
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

class PageState(Enum):
    """Enumeration of possible page states during execution."""
    READY = "READY"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    CAPTCHA_DETECTED = "CAPTCHA_DETECTED"
    RATE_LIMITED = "RATE_LIMITED"
    PAGE_TIMEOUT = "PAGE_TIMEOUT"
    DOM_STALLED = "DOM_STALLED"
    MODAL_BLOCKED = "MODAL_BLOCKED"
    COMMENT_BOX_MISSING = "COMMENT_BOX_MISSING"
    SUBMIT_BUTTON_MISSING = "SUBMIT_BUTTON_MISSING"
    UNKNOWN_PAGE_STATE = "UNKNOWN_PAGE_STATE"


@dataclass
class PageStateInfo:
    """Structured information about current page state."""
    state: PageState
    confidence: float  # 0.0 to 1.0
    details: Dict[str, str]
    screenshot_path: Optional[str] = None
    timestamp: Optional[str] = None


class PageStateDetector:
    """Detects and classifies current page state based on DOM analysis."""
    
    def __init__(self):
        self.state_patterns = {
            PageState.LOGIN_REQUIRED: [
                r'login',
                r'sign in',
                r'authenticat',
                r'account.*required'
            ],
            PageState.CAPTCHA_DETECTED: [
                r'captcha',
                r'verification.*code',
                r'challenge.*page',
                r'robot.*check'
            ],
            PageState.RATE_LIMITED: [
                r'rate.*limit',
                r'too many requests',
                r'slow down',
                r'retry later'
            ],
            PageState.PAGE_TIMEOUT: [
                r'timeout',
                r'page.*load.*fail',
                r'network.*error'
            ],
            PageState.DOM_STALLED: [
                r'loading.*stall',
                r'dom.*not loading',
                r'content.*not available'
            ],
            PageState.MODAL_BLOCKED: [
                r'modal.*blocked',
                r'popup.*prevented',
                r'stop.*popups'
            ],
            PageState.COMMENT_BOX_MISSING: [
                r'comment.*box.*missing',
                r'no.*comment.*area'
            ],
            PageState.SUBMIT_BUTTON_MISSING: [
                r'button.*submit.*missing',
                r'no.*submit.*button'
            ]
        }
    
    def detect_state(self, 
                    url: str, 
                    title: str, 
                    dom_summary: str, 
                    button_states: List[str],
                    modal_status: bool,
                    screenshot_path: Optional[str] = None) -> PageStateInfo:
        """
        Detect current page state based on collected information.
        
        Args:
            url: Current page URL
            title: Page title
            dom_summary: Summary of DOM content  
            button_states: List of button states
            modal_status: Whether modal is currently active
            screenshot_path: Path to screenshot if available
            
        Returns:
            PageStateInfo with detected state and confidence level
        """
        # Combine all information for analysis
        combined_info = f"{url} {title} {dom_summary} {' '.join(button_states)}"
        
        # Check for specific patterns
        detected_states = []
        
        for state, patterns in self.state_patterns.items():
            if self._check_patterns(combined_info, patterns):
                detected_states.append((state, 0.8))  # High confidence for direct matches
        
        # Handle special cases
        if modal_status:
            detected_states.append((PageState.MODAL_BLOCKED, 0.9))
            
        if not dom_summary or len(dom_summary.strip()) < 10:
            detected_states.append((PageState.DOM_STALLED, 0.7))
        
        # Return highest confidence detection or default
        if detected_states:
            best_state = max(detected_states, key=lambda x: x[1])
            return PageStateInfo(
                state=best_state[0],
                confidence=best_state[1],
                details={"source": "pattern_matching", "matched_patterns": [s[0] for s in detected_states]},
                screenshot_path=screenshot_path
            )
        
        # Default to READY if no specific issues found
        return PageStateInfo(
            state=PageState.READY,
            confidence=0.95,
            details={"source": "pattern_matching", "reason": "No specific patterns detected"},
            screenshot_path=screenshot_path
        )
    
    def _check_patterns(self, text: str, patterns: List[str]) -> bool:
        """Check if any pattern matches the given text."""
        text_lower = text.lower()
        for pattern in patterns:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return True
        return False
    
    def analyze_dom_features(self, dom_summary: str) -> Dict[str, bool]:
        """
        Analyze DOM content for specific features.
        Returns dictionary with feature detection results.
        """
        features = {}
        
        # Common UI elements to look for
        ui_elements = {
            'comment_box': ['comment', 'text area', 'input.*comment'],
            'submit_button': ['button.*submit', 'btn.*submit', 'send.*comment'],
            'login_form': ['login', 'username', 'password', 'sign in'],
            'captcha': ['captcha', 'robot', 'verification code']
        }
        
        for feature, patterns in ui_elements.items():
            # The _check_patterns now returns a bool directly, not a list
            result = self._check_patterns(dom_summary, patterns)
            features[feature] = result
            
        return features


# Example usage:
if __name__ == "__main__":
    detector = PageStateDetector()
    
    # Test with sample data
    test_state = detector.detect_state(
        url="https://www.tiktok.com/@user/video/123",
        title="TikTok - Video Title",
        dom_summary="User profile page with video content and comment section",
        button_states=["comment_button:enabled", "share_button:enabled"],
        modal_status=False
    )
    
    print(f"Detected state: {test_state.state.value}")
    print(f"Confidence: {test_state.confidence}")
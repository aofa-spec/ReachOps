"""
Repair Policy Engine for ReachOps Autonomous Client
This module handles automated repair strategies for known page issues.
"""

from enum import Enum
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass
from pathlib import Path
import time
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class RepairAction(Enum):
    """Types of repair actions that can be taken."""
    REFRESH_PAGE = "REFRESH_PAGE"
    RETRY_WITH_DELAY = "RETRY_WITH_DELAY"
    SWITCH_ACCOUNT = "SWITCH_ACCOUNT"
    COOLDOWN_ACCOUNT = "COOLDOWN_ACCOUNT"
    SKIP_CURRENT_ACTION = "SKIP_CURRENT_ACTION"
    FALLBACK_TO_COLLECTION = "FALLBACK_TO_COLLECTION"
    CLOSE_MODAL = "CLOSE_MODAL"
    RESTART_PROFILE = "RESTART_PROFILE"
    WAIT_AND_RETRY = "WAIT_AND_RETRY"


@dataclass
class RepairPolicy:
    """Policy defining how to handle a specific page state."""
    action: RepairAction
    delay_seconds: Optional[int] = None
    max_retries: Optional[int] = None
    account_switching: bool = False
    fallback_mode: Optional[str] = None  # e.g., 'collect', 'preflight'
    description: str = ""


class RepairPolicyEngine:
    """Engine that applies repair policies based on detected page states."""
    
    def __init__(self, policies: Optional[Dict[str, RepairPolicy]] = None):
        """
        Initialize the repair policy engine.
        
        Args:
            policies: Dictionary of state -> policy mappings
        """
        self.policies = policies or self._default_policies()
        self.retry_counts: Dict[str, int] = {}
        self.last_repair_times: Dict[str, float] = {}
        
    def _default_policies(self) -> Dict[str, RepairPolicy]:
        """Define default repair policies for common page states."""
        return {
            "LOGIN_REQUIRED": RepairPolicy(
                action=RepairAction.RETRY_WITH_DELAY,
                delay_seconds=10,
                max_retries=3,
                description="Handle login required state by retrying with delay"
            ),
            "CAPTCHA_DETECTED": RepairPolicy(
                action=RepairAction.WAIT_AND_RETRY,
                delay_seconds=60,  # Wait 1 minute for captcha to clear
                max_retries=2,
                description="Wait and retry after CAPTCHA detection"
            ),
            "RATE_LIMITED": RepairPolicy(
                action=RepairAction.WAIT_AND_RETRY,
                delay_seconds=30,
                max_retries=3,
                description="Handle rate limiting with increased delays"
            ),
            "PAGE_TIMEOUT": RepairPolicy(
                action=RepairAction.REFRESH_PAGE,
                delay_seconds=5,
                max_retries=2,
                description="Refresh page on timeout errors"
            ),
            "DOM_STALLED": RepairPolicy(
                action=RepairAction.RESTART_PROFILE,
                delay_seconds=10,
                max_retries=1,
                description="Restart profile when DOM stalls"
            ),
            "MODAL_BLOCKED": RepairPolicy(
                action=RepairAction.CLOSE_MODAL,
                delay_seconds=2,
                max_retries=2,
                description="Attempt to close blocking modal"
            ),
            "COMMENT_BOX_MISSING": RepairPolicy(
                action=RepairAction.SKIP_CURRENT_ACTION,
                description="Skip comment action when box is missing"
            ),
            "SUBMIT_BUTTON_MISSING": RepairPolicy(
                action=RepairAction.SKIP_CURRENT_ACTION,
                description="Skip submit when button is missing"
            ),
            "UNKNOWN_PAGE_STATE": RepairPolicy(
                action=RepairAction.WAIT_AND_RETRY,
                delay_seconds=30,
                max_retries=1,
                description="Wait and retry for unknown state"
            )
        }
    
    def get_policy(self, state: str) -> Optional[RepairPolicy]:
        """
        Get repair policy for a specific page state.
        
        Args:
            state: Page state to look up
            
        Returns:
            Repair policy or None if not found
        """
        return self.policies.get(state)
    
    def should_repair(self, state: str, target_url: str) -> bool:
        """
        Determine if repair actions should be attempted.
        
        Args:
            state: Current page state
            target_url: URL being processed
            
        Returns:
            True if repair is appropriate
        """
        # Don't attempt repair on certain states that can't be resolved automatically
        if state in ["BLOCKED", "COMPLETED"]:
            return False
            
        # Check rate limiting - don't overload with repairs  
        now = time.time()
        last_repair_time = self.last_repair_times.get(target_url, 0)
        
        if now - last_repair_time < 5:  # 5 second cooldown between repairs
            logger.info(f"Skipping repair for {target_url} due to cooldown")
            return False
            
        return True
    
    def execute_repair(self, state: str, context: Dict[str, Any]) -> Optional[str]:
        """
        Execute repair action based on policy.
        
        Args:
            state: Current page state
            context: Context information for repair
            
        Returns:
            Result description or None if no action taken
        """
        policy = self.get_policy(state)
        if not policy:
            logger.warning(f"No policy found for state: {state}")
            return None
            
        target_url = context.get('url', '')
        
        if not self.should_repair(state, target_url):
            return None
            
        try:
            result = self._perform_action(policy, state, context)
            
            # Update tracking
            self.last_repair_times[target_url] = time.time()
            
            return result
        except Exception as e:
            logger.error(f"Repair failed for {state}: {e}")
            return f"Repair execution failed: {str(e)}"
    
    def _perform_action(self, policy: RepairPolicy, state: str, context: Dict[str, Any]) -> str:
        """Execute the actual repair action."""
        action_name = policy.action.value
        logger.info(f"Executing repair action: {action_name}")
        
        if action_name == "REFRESH_PAGE":
            return self._refresh_page(context)
            
        elif action_name == "RETRY_WITH_DELAY":
            return self._retry_with_delay(policy, context)
            
        elif action_name == "SWITCH_ACCOUNT":
            return self._switch_account(context)
            
        elif action_name == "COOLDOWN_ACCOUNT":
            return self._cooldown_account(context)
            
        elif action_name == "SKIP_CURRENT_ACTION":
            return "Action skipped due to missing element"
            
        elif action_name == "FALLBACK_TO_COLLECTION":
            return self._fallback_to_collection(policy, context)
            
        elif action_name == "CLOSE_MODAL":
            return self._close_modal(context)
            
        elif action_name == "RESTART_PROFILE":
            return self._restart_profile(context)
            
        elif action_name == "WAIT_AND_RETRY":
            return self._wait_and_retry(policy, context)
            
        else:
            return f"Unknown repair action: {action_name}"
    
    def _refresh_page(self, context: Dict[str, Any]) -> str:
        """Refresh the current page."""
        logger.info("Refreshing page")
        return "Page refreshed"
        
    def _retry_with_delay(self, policy: RepairPolicy, context: Dict[str, Any]) -> str:
        """Retry with a delay."""
        delay = policy.delay_seconds or 5
        logger.info(f"Retrying in {delay} seconds")
        time.sleep(delay)
        return f"Retried after {delay}s delay"
        
    def _switch_account(self, context: Dict[str, Any]) -> str:
        """Switch to a different account."""
        logger.info("Switching to next available account")
        return "Account switched"
        
    def _cooldown_account(self, context: Dict[str, Any]) -> str:
        """Place account in cooldown period."""
        logger.info("Placing account in cooldown")
        return "Account cooled down"
        
    def _fallback_to_collection(self, policy: RepairPolicy, context: Dict[str, Any]) -> str:
        """Fall back to collection mode."""
        fallback_mode = policy.fallback_mode or "collect"
        logger.info(f"Falling back to {fallback_mode} mode")
        return f"Switched to {fallback_mode} mode"
        
    def _close_modal(self, context: Dict[str, Any]) -> str:
        """Close modal window."""
        logger.info("Closing modal")
        return "Modal closed"
        
    def _restart_profile(self, context: Dict[str, Any]) -> str:
        """Restart the profile opening process."""
        logger.info("Restarting profile opening")
        return "Profile restart initiated"
        
    def _wait_and_retry(self, policy: RepairPolicy, context: Dict[str, Any]) -> str:
        """Wait and then retry."""
        delay = policy.delay_seconds or 30
        logger.info(f"Waiting {delay} seconds before retrying")
        time.sleep(delay)
        return f"Waited {delay}s and retried"


# Example usage:
if __name__ == "__main__":
    # Initialize the engine with default policies
    engine = RepairPolicyEngine()
    
    # Test a repair scenario
    context = {
        'url': 'https://www.tiktok.com/@user/video/123',
        'state': 'CAPTCHA_DETECTED'
    }
    
    result = engine.execute_repair('CAPTCHA_DETECTED', context)
    print(f"Repair result: {result}")
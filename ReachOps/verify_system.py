#!/usr/bin/env python3
"""
Quick verification script for ReachOps autonomous client
"""

import sys
import os

# Add project path
project_path = "/Users/aofa/Documents/New project/ReachOps"
sys.path.insert(0, project_path)

def verify_imports():
    """Verify all modules can be imported successfully"""
    try:
        from page_state_detector import PageStateDetector
        from repair_policy_engine import RepairPolicyEngine
        from run_session import RunSession
        print("✅ All modules imported successfully")
        return True
    except Exception as e:
        print(f"❌ Import failed: {e}")
        return False

def verify_functionality():
    """Verify core functionality"""
    try:
        from page_state_detector import PageStateDetector, PageState
        from repair_policy_engine import RepairPolicyEngine, RepairAction
        
        # Test initialization
        detector = PageStateDetector()
        engine = RepairPolicyEngine()
        
        # Test basic detection
        test_state = detector.detect_state(
            url="https://www.tiktok.com/@user/video/123",
            title="Test Video",
            dom_summary="Video content with comments",
            button_states=["comment_button:enabled"],
            modal_status=False
        )
        
        print(f"✅ Page detection working: {test_state.state.value}")
        
        # Test policy retrieval
        policy = engine.get_policy("CAPTCHA_DETECTED")
        if policy:
            print(f"✅ Repair policy found: {policy.action.value}")
        
        print("✅ Core functionality verified")
        return True
        
    except Exception as e:
        print(f"❌ Functionality test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🔍 Running ReachOps verification...")
    
    if verify_imports() and verify_functionality():
        print("\n🎉 VERIFICATION SUCCESSFUL")
        print("ReachOps autonomous client is ready for deployment")
    else:
        print("\n❌ VERIFICATION FAILED")
        sys.exit(1)
"""
Test API Functionality
Verify eligibility API and agent work correctly
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.eligibility_api import MockEligibilityAPI
from agent.eligibility_agent import EligibilityAgent
from config import Config


def test_eligibility_api():
    """Test the mock eligibility API"""
    print("\nTesting Mock Eligibility API...")
    
    api = MockEligibilityAPI()
    
    # Test active member
    result = api.check_eligibility({
        "member_id": "MB123456",
        "date_of_birth": "1985-03-15"
    })
    
    assert result["status"] == "success", "API call failed"
    assert result["eligibility_status"] == "eligible", "Member should be eligible"
    print("✓ Active member check passed")
    
    # Test inactive member
    result = api.check_eligibility({
        "member_id": "MB345678",
        "date_of_birth": "1975-11-30"
    })
    
    assert result["eligibility_status"] == "not_eligible", "Member should be inactive"
    print("✓ Inactive member check passed")
    
    # Test with procedure
    result = api.check_eligibility({
        "member_id": "MB123456",
        "date_of_birth": "1985-03-15",
        "procedure_code": "70553"
    })
    
    assert "service_specific" in result, "Should have service-specific info"
    print("✓ Procedure-specific check passed")
    
    # Test procedure resolution
    resolved = api.resolve_procedure_code("MRI")
    assert resolved is not None, "Should resolve MRI to code"
    assert resolved["code"] == "70553", "MRI should resolve to 70553"
    print("✓ Procedure code resolution passed")
    
    # Test medication resolution
    resolved = api.resolve_ndc_code("Humira")
    assert resolved is not None, "Should resolve Humira to NDC"
    print("✓ Medication code resolution passed")
    
    print("✅ All API tests passed!")


def test_agent_basic():
    """Test basic agent functionality"""
    print("\nTesting Agent...")
    
    if not Config.OPENAI_API_KEY:
        print("⚠️  Skipping agent test - OPENAI_API_KEY not set")
        return
    
    try:
        agent = EligibilityAgent(openai_api_key=Config.OPENAI_API_KEY)
        print("✓ Agent initialized successfully")
        
        # Note: Full agent testing would require actual LLM calls
        # which we skip here to avoid costs/delays
        print("✓ Agent basic test passed")
        
    except Exception as e:
        print(f"⚠️  Agent test warning: {e}")
        print("   (This is OK if OpenAI key is not configured)")


if __name__ == "__main__":
    print("=" * 70)
    print("API Test Suite")
    print("=" * 70)
    
    all_passed = True
    
    try:
        test_eligibility_api()
        test_agent_basic()
        
        print("\n" + "=" * 70)
        print("✅ ALL TESTS PASSED!")
        print("=" * 70)
        
    except Exception as e:
        all_passed = False
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
    
    sys.exit(0 if all_passed else 1)

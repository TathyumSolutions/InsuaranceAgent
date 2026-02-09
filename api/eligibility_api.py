"""
Mock Insurance Eligibility API
Simulates real insurance eligibility verification responses
"""
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
import random


class MockEligibilityAPI:
    """
    Mock API that simulates insurance eligibility verification
    Based on standard X12 270/271 transaction format
    """
    
    def __init__(self):
        # Mock database of patients and their coverage
        self.mock_database = {
            "MB123456": {
                "member_id": "MB123456",
                "first_name": "John",
                "last_name": "Doe",
                "dob": "1985-03-15",
                "policy_number": "POL789456",
                "coverage_status": "active",
                "plan_type": "PPO",
                "effective_date": "2024-01-01",
                "termination_date": None,
                "copay_specialist": 40.00,
                "copay_primary": 25.00,
                "deductible_individual": 1500.00,
                "deductible_met": 450.00,
                "out_of_pocket_max": 6000.00,
                "out_of_pocket_met": 890.00
            },
            "MB789012": {
                "member_id": "MB789012",
                "first_name": "Jane",
                "last_name": "Smith",
                "dob": "1990-07-22",
                "policy_number": "POL456123",
                "coverage_status": "active",
                "plan_type": "HMO",
                "effective_date": "2023-06-01",
                "termination_date": None,
                "copay_specialist": 50.00,
                "copay_primary": 20.00,
                "deductible_individual": 2000.00,
                "deductible_met": 2000.00,
                "out_of_pocket_max": 7500.00,
                "out_of_pocket_met": 3200.00
            },
            "MB345678": {
                "member_id": "MB345678",
                "first_name": "Robert",
                "last_name": "Johnson",
                "dob": "1975-11-30",
                "policy_number": "POL123789",
                "coverage_status": "inactive",
                "plan_type": "PPO",
                "effective_date": "2022-01-01",
                "termination_date": "2023-12-31",
                "copay_specialist": 0,
                "copay_primary": 0,
                "deductible_individual": 0,
                "deductible_met": 0,
                "out_of_pocket_max": 0,
                "out_of_pocket_met": 0
            }
        }
        
        # Coverage for different procedure types
        self.procedure_coverage = {
            "99213": {"name": "Office Visit - Established Patient", "covered": True, "requires_auth": False},
            "99214": {"name": "Office Visit - Detailed", "covered": True, "requires_auth": False},
            "99285": {"name": "Emergency Department Visit", "covered": True, "requires_auth": False},
            "80053": {"name": "Comprehensive Metabolic Panel", "covered": True, "requires_auth": False},
            "71045": {"name": "Chest X-Ray", "covered": True, "requires_auth": False},
            "70450": {"name": "CT Head/Brain without Contrast", "covered": True, "requires_auth": True},
            "70553": {"name": "MRI Brain", "covered": True, "requires_auth": True},
            "27447": {"name": "Total Knee Replacement", "covered": True, "requires_auth": True},
            "J1745": {"name": "Infliximab Injection", "covered": True, "requires_auth": True},
            "J9035": {"name": "Bevacizumab Injection", "covered": False, "requires_auth": False},
            "G0438": {"name": "Annual Wellness Visit", "covered": True, "requires_auth": False}
        }
        
        # Drug coverage (NDC codes)
        self.drug_coverage = {
            "00002-7510-01": {"name": "Atorvastatin 20mg", "covered": True, "tier": 1, "copay": 10.00},
            "00069-0950-68": {"name": "Metformin 500mg", "covered": True, "tier": 1, "copay": 10.00},
            "00069-1530-01": {"name": "Lisinopril 10mg", "covered": True, "tier": 1, "copay": 10.00},
            "50090-3568-00": {"name": "Humira 40mg/0.8ml", "covered": True, "tier": 3, "copay": 150.00, "requires_auth": True},
            "00052-0602-02": {"name": "Eliquis 5mg", "covered": True, "tier": 2, "copay": 45.00},
            "12345-6789-00": {"name": "Experimental Drug XYZ", "covered": False, "tier": None, "copay": 0}
        }
    
    def check_eligibility(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Main eligibility check method
        
        Args:
            request: Dictionary containing eligibility check parameters
            
        Returns:
            Dictionary with eligibility response
        """
        member_id = request.get("member_id")
        dob = request.get("date_of_birth")
        service_type = request.get("service_type", "medical")  # medical, pharmacy, etc.
        procedure_code = request.get("procedure_code")
        ndc_code = request.get("ndc_code")
        service_date = request.get("service_date", datetime.now().strftime("%Y-%m-%d"))
        
        # Validate required fields
        if not member_id:
            return self._error_response("Missing required field: member_id")
        
        # Check if member exists
        member = self.mock_database.get(member_id)
        if not member:
            return self._error_response("Member not found", member_id)
        
        # Validate DOB if provided
        if dob and member["dob"] != dob:
            return self._error_response("Date of birth does not match records", member_id)
        
        # Check coverage status
        if member["coverage_status"] != "active":
            return self._inactive_coverage_response(member)
        
        # Check service date against coverage period
        service_dt = datetime.strptime(service_date, "%Y-%m-%d")
        effective_dt = datetime.strptime(member["effective_date"], "%Y-%m-%d")
        
        if service_dt < effective_dt:
            return self._error_response("Service date is before coverage effective date", member_id)
        
        # Build response based on service type
        if service_type == "pharmacy" and ndc_code:
            return self._pharmacy_eligibility_response(member, ndc_code, service_date)
        elif procedure_code:
            return self._medical_eligibility_response(member, procedure_code, service_date)
        else:
            return self._general_eligibility_response(member, service_date)
    
    def _general_eligibility_response(self, member: Dict, service_date: str) -> Dict[str, Any]:
        """General eligibility without specific procedure"""
        return {
            "status": "success",
            "eligibility_status": "eligible",
            "response_code": "200",
            "member_info": {
                "member_id": member["member_id"],
                "name": f"{member['first_name']} {member['last_name']}",
                "dob": member["dob"],
                "policy_number": member["policy_number"]
            },
            "coverage_info": {
                "status": "active",
                "plan_type": member["plan_type"],
                "effective_date": member["effective_date"],
                "termination_date": member["termination_date"]
            },
            "financial_info": {
                "deductible": {
                    "individual": member["deductible_individual"],
                    "met": member["deductible_met"],
                    "remaining": member["deductible_individual"] - member["deductible_met"]
                },
                "out_of_pocket": {
                    "max": member["out_of_pocket_max"],
                    "met": member["out_of_pocket_met"],
                    "remaining": member["out_of_pocket_max"] - member["out_of_pocket_met"]
                },
                "copays": {
                    "primary_care": member["copay_primary"],
                    "specialist": member["copay_specialist"]
                }
            },
            "service_date": service_date,
            "timestamp": datetime.now().isoformat()
        }
    
    def _medical_eligibility_response(self, member: Dict, procedure_code: str, service_date: str) -> Dict[str, Any]:
        """Eligibility response for specific medical procedure"""
        procedure_info = self.procedure_coverage.get(procedure_code)
        
        if not procedure_info:
            procedure_info = {
                "name": f"Unknown Procedure {procedure_code}",
                "covered": False,
                "requires_auth": False
            }
        
        deductible_remaining = member["deductible_individual"] - member["deductible_met"]
        
        response = self._general_eligibility_response(member, service_date)
        response["service_specific"] = {
            "procedure_code": procedure_code,
            "procedure_name": procedure_info["name"],
            "covered": procedure_info["covered"],
            "requires_prior_authorization": procedure_info.get("requires_auth", False),
            "benefit_details": self._calculate_benefit(member, procedure_info, deductible_remaining)
        }
        
        if not procedure_info["covered"]:
            response["eligibility_status"] = "not_covered"
            response["message"] = f"Procedure {procedure_code} ({procedure_info['name']}) is not covered under this plan"
        elif procedure_info.get("requires_auth"):
            response["eligibility_status"] = "eligible_with_conditions"
            response["message"] = "Prior authorization required for this procedure"
        
        return response
    
    def _pharmacy_eligibility_response(self, member: Dict, ndc_code: str, service_date: str) -> Dict[str, Any]:
        """Eligibility response for pharmacy/medication"""
        drug_info = self.drug_coverage.get(ndc_code)
        
        if not drug_info:
            drug_info = {
                "name": f"Unknown Medication {ndc_code}",
                "covered": False,
                "tier": None,
                "copay": 0
            }
        
        response = self._general_eligibility_response(member, service_date)
        response["service_type"] = "pharmacy"
        response["pharmacy_specific"] = {
            "ndc_code": ndc_code,
            "medication_name": drug_info["name"],
            "covered": drug_info["covered"],
            "formulary_tier": drug_info.get("tier"),
            "copay_amount": drug_info.get("copay", 0),
            "requires_prior_authorization": drug_info.get("requires_auth", False)
        }
        
        if not drug_info["covered"]:
            response["eligibility_status"] = "not_covered"
            response["message"] = f"Medication {drug_info['name']} is not covered under this plan's formulary"
        elif drug_info.get("requires_auth"):
            response["eligibility_status"] = "eligible_with_conditions"
            response["message"] = "Prior authorization required for this medication"
        
        return response
    
    def _calculate_benefit(self, member: Dict, procedure_info: Dict, deductible_remaining: float) -> Dict[str, Any]:
        """Calculate expected patient responsibility"""
        if not procedure_info["covered"]:
            return {
                "patient_responsibility": "Not covered",
                "estimated_cost": 0,
                "notes": "This service is not covered under the plan"
            }
        
        # Simplified benefit calculation
        if deductible_remaining > 0:
            return {
                "patient_responsibility": f"Deductible + Coinsurance",
                "deductible_applies": True,
                "deductible_remaining": deductible_remaining,
                "notes": "Patient must meet deductible before insurance coverage begins"
            }
        else:
            copay = member.get("copay_specialist", 40.00) if "surgery" in procedure_info["name"].lower() else member.get("copay_primary", 25.00)
            return {
                "patient_responsibility": f"Copay: ${copay:.2f}",
                "deductible_applies": False,
                "copay_amount": copay,
                "notes": "Deductible has been met"
            }
    
    def _inactive_coverage_response(self, member: Dict) -> Dict[str, Any]:
        """Response for inactive coverage"""
        return {
            "status": "success",
            "eligibility_status": "not_eligible",
            "response_code": "201",
            "member_info": {
                "member_id": member["member_id"],
                "name": f"{member['first_name']} {member['last_name']}",
                "dob": member["dob"]
            },
            "coverage_info": {
                "status": "inactive",
                "termination_date": member["termination_date"]
            },
            "message": "Coverage is not active. Please contact member services.",
            "timestamp": datetime.now().isoformat()
        }
    
    def _error_response(self, message: str, member_id: str = None) -> Dict[str, Any]:
        """Error response"""
        return {
            "status": "error",
            "response_code": "400",
            "message": message,
            "member_id": member_id,
            "timestamp": datetime.now().isoformat()
        }
    
    def resolve_procedure_code(self, name: str) -> Optional[Dict[str, str]]:
        """
        Resolve a procedure name to a CPT code using fuzzy matching.
        Returns {"code": "70553", "name": "MRI Brain"} or None.
        """
        name_lower = name.lower().strip()
        for code, info in self.procedure_coverage.items():
            procedure_name_lower = info["name"].lower()
            # Exact or substring match in either direction
            if (name_lower in procedure_name_lower
                or procedure_name_lower in name_lower
                or any(word in procedure_name_lower for word in name_lower.split() if len(word) >= 2)):
                return {"code": code, "name": info["name"]}
        return None

    def resolve_ndc_code(self, name: str) -> Optional[Dict[str, str]]:
        """
        Resolve a medication name to an NDC code using fuzzy matching.
        Returns {"code": "50090-3568-00", "name": "Humira 40mg/0.8ml"} or None.
        """
        name_lower = name.lower().strip()
        for code, info in self.drug_coverage.items():
            drug_name_lower = info["name"].lower()
            if (name_lower in drug_name_lower
                or drug_name_lower in name_lower
                or any(word in drug_name_lower for word in name_lower.split() if len(word) >= 2)):
                return {"code": code, "name": info["name"]}
        return None

    def get_available_procedures(self) -> list:
        """Get list of all known procedures with codes"""
        return [
            {"code": code, "name": info["name"], "covered": info["covered"], "requires_auth": info.get("requires_auth", False)}
            for code, info in self.procedure_coverage.items()
        ]

    def get_available_medications(self) -> list:
        """Get list of all known medications with NDC codes"""
        return [
            {"ndc_code": code, "name": info["name"], "covered": info["covered"], "tier": info.get("tier")}
            for code, info in self.drug_coverage.items()
        ]

    def get_available_members(self) -> list:
        """Helper method to get list of available test member IDs"""
        return [
            {
                "member_id": mid,
                "name": f"{info['first_name']} {info['last_name']}",
                "status": info["coverage_status"]
            }
            for mid, info in self.mock_database.items()
        ]

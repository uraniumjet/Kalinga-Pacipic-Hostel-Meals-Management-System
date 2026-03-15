from datetime import datetime

def get_current_meal(student=None, ramadan_mode=False):
    hour = datetime.now().hour
    
    # If Ramadan mode is ON and student is Muslim
    if ramadan_mode and student and student.religion == 'muslim':
        if 3 <= hour <= 5: return "Suhoor"
        if 18 <= hour <= 20: return "Iftar"
        return None # No lunch during Ramadan for fasting students

    # Standard Meal Windows
    if 6 <= hour <= 10: return "breakfast"
    if 12 <= hour <= 15: return "lunch"
    if 18 <= hour <= 21: return "dinner"
    
    return None
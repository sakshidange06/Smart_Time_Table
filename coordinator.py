
def route_request(choice):
    if choice == "quiz":
        print("Routing to Quiz Agent...")
        return "Quiz Agent Called"
    elif choice == "timetable":
        print("Routing to Timetable Agent...")
        return "Timetable Agent Called"
    else:
        return "Invalid choice"
    

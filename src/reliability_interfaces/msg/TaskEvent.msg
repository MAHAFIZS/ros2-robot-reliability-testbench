# Explicit task observability; independent of action transport implementation.
builtin_interfaces/Time stamp
string session_id
uint64 sequence
# Action UUID hex; idle reset uses reset:<operation UUID>.
string goal_id
# ACCEPTED, TARGET, CANCELED, TIMEOUT, ABORTED, COMPLETED, RESET
string event
# succeeded, canceled, timeout, reset, aborted; meaningful on terminal events.
string outcome
uint64 generation
geometry_msgs/Point target
# Terminal snapshot matches the action result, before a reset restores state.
bool has_position
geometry_msgs/Point position
float64 final_error
float64 elapsed_simulation_seconds
# Same-process monotonic duration, not an epoch timestamp.
float64 elapsed_wall_seconds
float64 tolerance
string detail

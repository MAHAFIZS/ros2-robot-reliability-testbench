cmake_minimum_required(VERSION 3.8)
project(reliability_interfaces)
find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(builtin_interfaces REQUIRED)
rosidl_generate_interfaces(${PROJECT_NAME}
  "action/Reach.action" "msg/SimulationState.msg" "msg/TaskEvent.msg"
  "msg/ObservedState.msg" "msg/TaskIntent.msg" "msg/FaultConfiguration.msg"
  "msg/FaultEvent.msg" "msg/CommandEvent.msg" "msg/DiagnosticEvent.msg"
  "srv/ConfigureFaults.srv" "srv/MonitorStatus.srv"
  "srv/Control.srv" "srv/Reset.srv" "srv/Health.srv"
  DEPENDENCIES geometry_msgs builtin_interfaces)
ament_export_dependencies(rosidl_default_runtime)
ament_package()

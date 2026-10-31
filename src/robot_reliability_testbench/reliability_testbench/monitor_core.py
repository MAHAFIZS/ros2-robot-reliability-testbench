"""Independent health rules. No simulator, raw-state or fault-configuration access."""
import math


class MonitorCore:
    def __init__(self, emit, started, freshness=.15, progress_window=.20, movement=.001, startup_grace=.30):
        self.emit_callback = emit
        self.started = started
        self.freshness = freshness
        self.progress_window = progress_window
        self.movement = movement
        self.startup_grace = startup_grace
        self.received = None
        self.observation = None
        self.intent = None
        self.reference = None
        self.alerts = set()
        self.observations = 0
        self.clock = 0.

    def emit(self, code, active, now, evidence, missing=0, window=0., displacement=0., distance=0., recovered=''):
        obs = self.observation
        self.emit_callback(dict(reason_code=code, active=active, recovered_reason=recovered,
            goal_id=self.intent['goal_id'] if self.intent else '',
            generation=obs['generation'] if obs else 0,
            observation_sequence=obs['sequence'] if obs else 0,
            missing_count=missing, observation_age_steady_seconds=0. if self.received is None else now-self.received,
            window_simulation_seconds=window, displacement_metres=displacement,
            distance_metres=distance, evidence=evidence, simulation_time=self.clock))

    def clear_progress(self, now, code='NO_PROGRESS_CLEARED', evidence='Intent ended or generation changed'):
        self.reference = None
        if 'NO_PROGRESS' in self.alerts:
            self.alerts.remove('NO_PROGRESS')
            self.emit(code, False, now, evidence, recovered='NO_PROGRESS')

    def task_intent(self, intent, now):
        previous = self.intent
        self.intent = intent
        if not intent['active'] or (previous and (previous['goal_id'], previous['generation']) !=
                                   (intent['goal_id'], intent['generation'])):
            self.clear_progress(now)

    def observe(self, observation, now):
        if not all(math.isfinite(v) for v in observation['position'] + observation['joints'] + [observation['time']]):
            if 'INVALID_OBSERVATION' not in self.alerts:
                self.alerts.add('INVALID_OBSERVATION')
                self.emit('INVALID_OBSERVATION', True, now, 'Nonfinite affected observation')
            return
        previous = self.observation
        if previous and observation['generation'] < previous['generation']:
            return
        if previous and observation['generation'] == previous['generation']:
            if observation['sequence'] <= previous['sequence']:
                self.emit('SEQUENCE_ERROR', True, now, 'Nonincreasing source sequence')
                return
        self.observation = observation
        self.received = now
        self.observations += 1
        if previous and observation['generation'] == previous['generation']:
            missing = observation['sequence'] - previous['sequence'] - 1
            if missing:
                self.emit('OBSERVATION_GAP', True, now, 'Source sequence skipped; cause is not identifiable', missing=missing)
        else:
            self.clear_progress(now)
        for reason in ('STALE_OBSERVATIONS', 'INVALID_OBSERVATION'):
            if reason in self.alerts:
                self.alerts.remove(reason)
                self.emit('OBSERVATIONS_RECOVERED', False, now, 'Valid observation received', recovered=reason)
        self.check_progress(now)

    def check_progress(self, now):
        obs, intent = self.observation, self.intent
        if not obs or not intent or not intent['active'] or obs['generation'] != intent['generation']:
            return
        error = math.dist(obs['position'], intent['target'])
        if error <= intent['tolerance']:
            self.clear_progress(now, 'PROGRESS_RECOVERED', 'Affected position is within target tolerance')
            return
        if self.reference is None:
            self.reference = (obs['time'], obs['position'], error)
            return
        stamp, position, initial_error = self.reference
        displacement = math.dist(position, obs['position'])
        window = obs['time']-stamp
        if displacement >= self.movement or initial_error-error >= self.movement:
            self.reference = (obs['time'], obs['position'], error)
            if 'NO_PROGRESS' in self.alerts:
                self.alerts.remove('NO_PROGRESS')
                self.emit('PROGRESS_RECOVERED', False, now, 'Movement observed',
                          window=window, displacement=displacement, distance=error, recovered='NO_PROGRESS')
        elif window + 1e-9 >= self.progress_window and 'NO_PROGRESS' not in self.alerts:
            self.alerts.add('NO_PROGRESS')
            self.emit('NO_PROGRESS', True, now,
                'Active target outside tolerance; no significant observed displacement/error reduction. '
                'Sensor freeze, command delay or stalled motion cannot be distinguished.',
                window=window, displacement=displacement, distance=error)

    def tick(self, now):
        age = now - (self.received if self.received is not None else self.started)
        eligible = self.received is not None or now-self.started >= self.startup_grace
        if eligible and age > self.freshness and 'STALE_OBSERVATIONS' not in self.alerts:
            self.alerts.add('STALE_OBSERVATIONS')
            self.emit('STALE_OBSERVATIONS', True, now, 'No valid affected observation within steady freshness threshold')

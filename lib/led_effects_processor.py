import math
import time
from lib.rpi_drivers import Color


class LEDEffectsProcessor:
    def __init__(self, ledstrip, ledsettings, menu, color_mode, last_sustain, pedal_deadzone, runtime_diagnostics=None):
        self.ledstrip = ledstrip
        self.ledsettings = ledsettings
        self.menu = menu
        self.color_mode = color_mode
        self.last_sustain = last_sustain
        self.pedal_deadzone = pedal_deadzone
        self.runtime_diagnostics = runtime_diagnostics
        self._pulse_rgb = [[0.0, 0.0, 0.0] for _ in range(ledstrip.led_number)]
        self._pulse_seen = [False] * ledstrip.led_number
        self._pulse_touched = []

    def process_fade_effects(self, event_loop_time):
        any_led_changed = False
        active_leds = 0
        ledstrip = self.ledstrip
        ledsettings = self.ledsettings
        keylist = ledstrip.keylist
        keylist_status = ledstrip.keylist_status
        keylist_sustained = ledstrip.keylist_sustained
        keylist_color = ledstrip.keylist_color
        external_software = getattr(ledstrip, "keylist_external_software", None)
        guide_lights = getattr(ledstrip, "keylist_guide", None)
        use_hand_colors = getattr(ledsettings, "skipped_notes", "Normal") != "Finger-based"
        mode = ledsettings.mode
        color_update = self.color_mode.ColorUpdate
        set_pixel_color = ledstrip.strip.setPixelColor
        set_adjacent_colors = ledstrip.set_adjacent_colors
        screensaver_is_running = self.menu.screensaver_is_running
        sustain_value = getattr(ledstrip, "sustain_value", self.last_sustain)
        has_active_pulses = (mode == "Pulse" and bool(ledstrip.active_pulses))

        if mode == "Fading":
            speed = ledsettings.fadingspeed
        elif mode == "Velocity":
            speed = ledsettings.velocity_speed
        elif mode == "Pedal":
            speed = ledsettings.pedal_speed
        else:
            speed = ledsettings.fadingspeed

        decrease_amount = max(0.0, event_loop_time) * 1000000.0 / max(1.0, float(speed))

        # Resolve active key indices in O(K) via ActiveIndexList (with safe fallback for mock lists)
        active_indices_set = getattr(keylist, "active_indices", None)
        if active_indices_set is not None:
            if not active_indices_set and not has_active_pulses:
                if self.runtime_diagnostics is not None:
                    self.runtime_diagnostics.set_gauge("active_leds", 0)
                return False
            candidate_indices = tuple(active_indices_set) if active_indices_set else ()
        else:
            candidate_indices = tuple(i for i, s in enumerate(keylist) if s > 0)
            if not candidate_indices and not has_active_pulses:
                if self.runtime_diagnostics is not None:
                    self.runtime_diagnostics.set_gauge("active_leds", 0)
                return False

        is_velocity_or_pedal = mode in ("Velocity", "Pedal")
        is_fading_mode = (mode == "Fading")
        sustain_on = int(sustain_value) >= self.pedal_deadzone
        cached_backlight_rgb = None

        for n in candidate_indices:
            strength = keylist[n]
            if strength <= 0:
                if active_indices_set is not None:
                    active_indices_set.discard(n)
                continue

            active_leds += 1
            red, green, blue = keylist_color[n]
            led_changed = False

            if not (use_hand_colors and external_software and external_software[n] == 1):
                new_color = color_update(None, n, (red, green, blue))
                if new_color is not None:
                    red, green, blue = new_color
                    led_changed = True

            fading = 1.0
            is_guide = bool(guide_lights and guide_lights[n] == 1)
            if not is_guide and (is_velocity_or_pedal or (is_fading_mode and keylist_status[n] == 0)):
                fading = strength * 0.001
                red = int(red * fading)
                green = int(green * fading)
                blue = int(blue * fading)
                new_strength = strength - decrease_amount
                if new_strength > 0:
                    keylist[n] = new_strength
                else:
                    keylist[n] = 0
                led_changed = True

            if not is_guide and is_velocity_or_pedal:
                key_active = keylist_status[n] == 1 or keylist_sustained[n] == 1
                if sustain_on and not key_active:
                    keylist[n] = 1000
                    led_changed = True
                elif not sustain_on and not key_active:
                    keylist[n] = 0
                    red, green, blue = (0, 0, 0)
                    led_changed = True

            if keylist[n] <= 0 and screensaver_is_running is not True:
                if cached_backlight_rgb is None:
                    backlight_level = float(ledsettings.backlight_brightness_percent) / 100.0
                    cached_backlight_rgb = (
                        int(ledsettings.get_backlight_color("Red")) * backlight_level,
                        int(ledsettings.get_backlight_color("Green")) * backlight_level,
                        int(ledsettings.get_backlight_color("Blue")) * backlight_level,
                    )
                red, green, blue = cached_backlight_rgb
                led_changed = True

            if led_changed:
                color = Color(int(red), int(green), int(blue))
                set_pixel_color(n, color)
                set_adjacent_colors(n, color, False, fading)
                any_led_changed = True
        
        if mode == "Pulse":
            if self.process_pulse_effects():
                any_led_changed = True

        if self.runtime_diagnostics is not None:
            self.runtime_diagnostics.set_gauge("active_leds_last", active_leds)
            self.runtime_diagnostics.set_gauge("active_pulses_last", len(ledstrip.active_pulses))

        return any_led_changed

    def process_pulse_effects(self):
        if not self.ledstrip.active_pulses:
            return False

        if len(self._pulse_rgb) != self.ledstrip.led_number:
            self._pulse_rgb = [[0.0, 0.0, 0.0] for _ in range(self.ledstrip.led_number)]
            self._pulse_seen = [False] * self.ledstrip.led_number
            self._pulse_touched.clear()
        current_time = time.perf_counter()
        pulses_to_remove = []
        surviving_pulses = []
        pulse_rgb = self._pulse_rgb
        pulse_seen = self._pulse_seen
        touched_leds = self._pulse_touched

        def touch_led(index):
            if not pulse_seen[index]:
                pulse_seen[index] = True
                touched_leds.append(index)
            return pulse_rgb[index]
        
        max_dist = self.ledsettings.pulse_animation_distance
        duration = max(1.0, self.ledsettings.pulse_animation_speed) / 1000.0
        flicker_strength = self.ledsettings.pulse_flicker_strength / 100.0
        
        # Base background color (backlight) to blend on top of
        if not self.menu.screensaver_is_running:
            backlight_level = float(self.ledsettings.backlight_brightness_percent) / 100
            br = int(self.ledsettings.get_backlight_color("Red")) * backlight_level
            bg = int(self.ledsettings.get_backlight_color("Green")) * backlight_level
            bb = int(self.ledsettings.get_backlight_color("Blue")) * backlight_level
        else:
            br, bg, bb = 0, 0, 0

        for pulse in self.ledstrip.active_pulses:
            state = pulse.get("state", "attack")
            start_time = pulse["start_time"]
            velocity = pulse["velocity"]
            center = pulse["position"]
            p_r, p_g, p_b = pulse["color"]
            
            elapsed = current_time - start_time
            
            # Determine progress and effective radius
            
            # Attack/Expansion Phase
            # Always calculate outer radius based on time since start to keep it consistent
            attack_progress = elapsed / duration
            if attack_progress > 1.0: attack_progress = 1.0
            
            # Quadratic Ease-out for expansion
            ease_out_progress = attack_progress * (2 - attack_progress)
            current_outer_radius = ease_out_progress * max_dist
            
            # Determine inner radius (for release phase)
            current_inner_radius = 0.0
            
            if state == "release":
                release_time = pulse.get("release_time", current_time)
                release_elapsed = current_time - release_time
                release_progress = release_elapsed / duration
                
                if release_progress >= 1.0:
                    pulses_to_remove.append(pulse)
                    continue

                # Linear expansion of the "hole"
                current_inner_radius = release_progress * max_dist

            surviving_pulses.append(pulse)
            
            # Flicker (Sustain Phase)
            # If fully expanded and not yet in release (or early release), add flicker
            current_intensity = velocity
            
            if attack_progress >= 1.0 and state != "release":
                # Sustain phase - apply flicker
                # Simple sine wave flicker
                v_val = (math.sin(current_time * self.ledsettings.pulse_flicker_speed) + 1) / 2  # 0 to 1
                # Modulate intensity down by strength
                current_intensity = velocity * (1.0 - (flicker_strength * v_val))
                
                # Update state to sustain if implicit transition
                if pulse.get("state") == "attack":
                     pulse["state"] = "sustain"
            
            # Determine range to update
            # We update the full max_dist range to ensure we clear previous frames' pixels
            start_led = max(0, int(center - max_dist - 2))
            end_led = min(self.ledstrip.led_number, int(center + max_dist + 3))
            
            for i in range(start_led, end_led):
                dist = abs(i - center)
                
                # Initialize with 0 (background will be added later) if not already visited
                color = touch_led(i)

                # Check if pixel is within the active band (inner < dist < outer)
                if dist < current_inner_radius or dist > current_outer_radius:
                    continue
                
                if current_outer_radius < 0.01:
                    dist_intensity = 1.0 if dist < 0.5 else 0
                else:
                    # Linear falloff from center to outer radius
                    dist_intensity = max(0.0, 1.0 - (dist / current_outer_radius))
                
                final_intensity = current_intensity * dist_intensity
                
                if final_intensity > 0.005:
                    color[0] += p_r * final_intensity
                    color[1] += p_g * final_intensity
                    color[2] += p_b * final_intensity

        # Process "dying" pulses one last time to clear their area
        for pulse in pulses_to_remove:
             center = pulse["position"]
             start_led = max(0, int(center - max_dist - 2))
             end_led = min(self.ledstrip.led_number, int(center + max_dist + 3))
             
             for i in range(start_led, end_led):
                 touch_led(i)

        for i in touched_leds:
            color = pulse_rgb[i]
            final_r = min(255, int(color[0] + br))
            final_g = min(255, int(color[1] + bg))
            final_b = min(255, int(color[2] + bb))

            pixel_color = Color(final_r, final_g, final_b)
            self.ledstrip.strip.setPixelColor(i, pixel_color)
            self.ledstrip.set_adjacent_colors(i, pixel_color, False)
            color[0] = color[1] = color[2] = 0.0
            pulse_seen[i] = False

        touched_leds.clear()

        if pulses_to_remove:
            self.ledstrip.active_pulses = surviving_pulses

        return True
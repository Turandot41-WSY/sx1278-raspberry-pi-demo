#ifndef SX1278_PROFILE_CONTROL_H
#define SX1278_PROFILE_CONTROL_H

#include <stdint.h>

#include "protocol_types.h"

namespace sx1278 {

// ProfileControl is the configuration surface consumed by the experiment controller.
class ProfileControl {
public:
    /** Release one concrete profile controller through its base class. */
    virtual ~ProfileControl() {}

    /** Apply and verify one complete generated profile by protocol code.
     *
     */
    virtual bool apply_profile(uint8_t profile_code) = 0;

    /** Apply one generated PA row and require the caller's exact RegOcp.
     *
     */
    virtual bool apply_pa(int8_t command_dbm, uint8_t requested_ocp) = 0;

    /** Return whether a complete profile has passed hardware readback. */
    virtual bool profile_configured() const = 0;

    /** Return whether PA, PaDac, and OCP have passed hardware readback. */
    virtual bool pa_configured() const = 0;

    /** Invalidate both configuration proofs after a hardware-level reset. */
    virtual void invalidate_configuration() = 0;

    /** Return the active profile code or 0xFF when no profile is valid. */
    virtual uint8_t active_profile() const = 0;

    /** Return the last successfully applied PA command in dBm. */
    virtual int8_t pa_command_dbm() const = 0;

    /** Return the last successfully applied RegPaConfig byte. */
    virtual uint8_t reg_pa_config() const = 0;

    /** Return the last successfully applied RegPaDac byte. */
    virtual uint8_t reg_pa_dac() const = 0;

    /** Return the last successfully applied RegOcp byte. */
    virtual uint8_t reg_ocp() const = 0;

    /** Return the number of valid address/readback pairs, at most 55. */
    virtual uint8_t readback_count() const = 0;

    /** Return the fixed address/readback pair buffer owned by this object. */
    virtual const uint8_t* readback_pairs() const = 0;

    /** Return the most recent fail-closed profile or PA error. */
    virtual ErrorCode last_error() const = 0;

    /** Copy the generated 32-byte profile-table SHA-256 identity. */
    virtual void copy_table_hash(uint8_t output[32]) const = 0;
};

}  // namespace sx1278

#endif

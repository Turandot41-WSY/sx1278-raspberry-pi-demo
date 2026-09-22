#ifndef SX1278_PROFILE_MANAGER_H
#define SX1278_PROFILE_MANAGER_H

#include <stdint.h>

#include "profile_control.h"
#include "sx1278_driver.h"

namespace sx1278 {

class ProfileManager : public ProfileControl {
public:
    /** Bind generated configuration tables to one raw SX1278 driver. */
    explicit ProfileManager(Sx1278Driver& radio);

    /** Apply every generated row and publish only a fully verified profile.
     *
     *
     * Processing flow:
     *   code/slice checks -> ordered masked writes -> Standby -> atomic publish
     */
    bool apply_profile(uint8_t profile_code) override;

    /** Apply one exact generated PA/OCP row and publish it after readback.
     *
     *
     * Processing flow:
     *   command lookup -> requested-OCP match -> hardware checks -> publish
     */
    bool apply_pa(int8_t command_dbm, uint8_t requested_ocp) override;

    /** Return whether all active-profile writes passed masked readback. */
    bool profile_configured() const override;

    /** Return whether all active PA/OCP writes passed exact readback. */
    bool pa_configured() const override;

    /** Discard both configuration proofs after a hardware-level reset. */
    void invalidate_configuration() override;

    /** Return the active profile code or 0xFF when profile state is invalid. */
    uint8_t active_profile() const override;

    /** Return the last successfully applied PA command in dBm. */
    int8_t pa_command_dbm() const override;

    /** Return the last successfully applied RegPaConfig byte. */
    uint8_t reg_pa_config() const override;

    /** Return the last successfully applied RegPaDac byte. */
    uint8_t reg_pa_dac() const override;

    /** Return the last successfully applied RegOcp byte. */
    uint8_t reg_ocp() const override;

    /** Return the number of verified register pairs for the active profile. */
    uint8_t readback_count() const override;

    /** Return the fixed address/readback buffer for CONFIG_REPORT. */
    const uint8_t* readback_pairs() const override;

    /** Return the last profile or PA configuration error. */
    ErrorCode last_error() const override;

    /** Copy the generated profile-table identity without direct flash access.
     *
     *
     * Processing flow:
     *   output check -> 32 bounded PROGMEM reads -> caller buffer
     */
    void copy_table_hash(uint8_t output[32]) const override;

private:
    Sx1278Driver& radio_;
    uint8_t profile_;
    int8_t pa_;
    uint8_t pa_config_;
    uint8_t pa_dac_;
    uint8_t ocp_;
    uint8_t count_;
    ErrorCode error_;
    bool profile_configured_;
    bool pa_configured_;
    uint8_t readbacks_[110];
};

}  // namespace sx1278

#endif

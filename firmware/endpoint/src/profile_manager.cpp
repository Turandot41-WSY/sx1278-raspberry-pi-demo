#include "profile_manager.h"

#include <stddef.h>

#include "generated/pa_table.h"
#include "generated/profile_table.h"
#include "sx1278_registers.h"

namespace sx1278 {

ProfileManager::ProfileManager(Sx1278Driver& radio) : radio_(radio) {
    profile_ = 0xFFU;
    pa_ = 0;
    pa_config_ = 0U;
    pa_dac_ = 0U;
    ocp_ = 0U;
    count_ = 0U;
    error_ = ErrorCode::None;
    profile_configured_ = false;
    pa_configured_ = false;
}

bool ProfileManager::apply_profile(uint8_t profile_code) {
    profile_ = 0xFFU;
    count_ = 0U;
    error_ = ErrorCode::Profile;
    profile_configured_ = false;
    pa_configured_ = false;
    if (profile_code >= generated::kProfileCount) {
        return false;
    }

    generated::ProfileSlice slice = {};
    if (!generated::read_profile_slice(profile_code, &slice)) {
        return false;
    }
    if (slice.profile_code != profile_code) {
        return false;
    }
    if (slice.count == 0U) {
        return false;
    }
    if (slice.count > 55U) {
        return false;
    }
    uint16_t end_index = slice.first;
    end_index += slice.count;
    if (end_index > generated::kRegisterSettingCount) {
        return false;
    }

    size_t pair_index = 0U;
    for (uint8_t row_index = 0U; row_index < slice.count; ++row_index) {
        uint16_t absolute_index = slice.first;
        absolute_index += row_index;
        generated::RegisterSetting row = {};
        bool row_loaded = generated::read_register_setting(absolute_index, &row);
        if (!row_loaded) {
            return false;
        }
        if (row.profile_code != profile_code) {
            return false;
        }

        uint8_t actual = 0U;
        bool write_ok = false;
        if (row.address == reg::OpMode) {
            write_ok = radio_.configure_profile_op_mode(
                row.write_value,
                row.readback_mask,
                row.expected_readback
            );
            if (write_ok) {
                actual = radio_.read_register(reg::OpMode);
            }
        } else {
            write_ok = radio_.write_checked(
                row.address,
                row.write_value,
                row.readback_mask,
                row.expected_readback,
                &actual
            );
        }
        if (!write_ok) {
            error_ = ErrorCode::RegisterReadback;
            return false;
        }
        readbacks_[pair_index] = row.address;
        pair_index += 1U;
        readbacks_[pair_index] = actual;
        pair_index += 1U;
    }

    if (!radio_.standby()) {
        error_ = ErrorCode::RegisterReadback;
        return false;
    }
    profile_ = profile_code;
    count_ = slice.count;
    error_ = ErrorCode::None;
    profile_configured_ = true;
    return true;
}

bool ProfileManager::apply_pa(int8_t command_dbm, uint8_t requested_ocp) {
    pa_configured_ = false;
    if (!profile_configured_) {
        error_ = ErrorCode::Pa;
        return false;
    }
    generated::PaSetting setting = {};
    bool found = generated::find_pa_setting(command_dbm, &setting);
    if (!found) {
        error_ = ErrorCode::Pa;
        return false;
    }
    if (setting.reg_ocp != requested_ocp) {
        error_ = ErrorCode::Pa;
        return false;
    }
    bool applied = radio_.set_pa_registers(
        setting.reg_pa_config,
        setting.reg_pa_dac,
        setting.reg_ocp
    );
    if (!applied) {
        error_ = ErrorCode::RegisterReadback;
        return false;
    }
    pa_ = setting.command_dbm;
    pa_config_ = setting.reg_pa_config;
    pa_dac_ = setting.reg_pa_dac;
    ocp_ = setting.reg_ocp;
    error_ = ErrorCode::None;
    pa_configured_ = true;
    return true;
}

bool ProfileManager::profile_configured() const {
    return profile_configured_;
}

bool ProfileManager::pa_configured() const {
    return pa_configured_;
}

void ProfileManager::invalidate_configuration() {
    profile_ = 0xFFU;
    count_ = 0U;
    profile_configured_ = false;
    pa_configured_ = false;
    error_ = ErrorCode::None;
}

uint8_t ProfileManager::active_profile() const {
    return profile_;
}

int8_t ProfileManager::pa_command_dbm() const {
    return pa_;
}

uint8_t ProfileManager::reg_pa_config() const {
    return pa_config_;
}

uint8_t ProfileManager::reg_pa_dac() const {
    return pa_dac_;
}

uint8_t ProfileManager::reg_ocp() const {
    return ocp_;
}

uint8_t ProfileManager::readback_count() const {
    return count_;
}

const uint8_t* ProfileManager::readback_pairs() const {
    return readbacks_;
}

ErrorCode ProfileManager::last_error() const {
    return error_;
}

void ProfileManager::copy_table_hash(uint8_t output[32]) const {
    if (output == 0) {
        return;
    }
    for (uint8_t index = 0U; index < 32U; ++index) {
        uint8_t value = 0U;
        bool read_ok = generated::read_profile_hash_byte(index, &value);
        if (!read_ok) {
            return;
        }
        output[index] = value;
    }
}

}  // namespace sx1278

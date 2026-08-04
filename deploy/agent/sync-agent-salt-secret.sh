#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
    echo "Run this script as root on the Uyuni container host." >&2
    exit 1
fi

env_file=/root/UyuniAI/.env
secret=$(
    podman exec uyuni-server python3 -c \
        'from spacewalk.common.rhnConfig import cfg_component
with cfg_component("server") as config:
    print(config.secret_key, end="")'
)

if [[ -z ${secret} ]]; then
    echo "Uyuni server secret was not found." >&2
    exit 1
fi

install -o root -g root -m 0600 /dev/null "${env_file}.new"
found=false
while IFS= read -r line || [[ -n ${line} ]]; do
    if [[ ${line} == SALT_API_PASSWORD=* ]]; then
        printf 'SALT_API_PASSWORD=%s\n' "${secret}" >> "${env_file}.new"
        found=true
    else
        printf '%s\n' "${line}" >> "${env_file}.new"
    fi
done < "${env_file}"
if [[ ${found} == false ]]; then
    printf 'SALT_API_PASSWORD=%s\n' "${secret}" >> "${env_file}.new"
fi
mv "${env_file}.new" "${env_file}"
chmod 0600 "${env_file}"

unset secret
echo "Agent Salt API secret synchronized without displaying it."

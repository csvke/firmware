#!/usr/bin/haserl
<%in p/common.cgi %>
<%
page_title="TXW8301 HaLow WiFi"
config_file=/etc/hgicf.conf
backup_file=/tmp/hgicf.conf.bak
params="mode ssid key_mgmt freq_range chan_list bss_bw tx_mcs dhcpc"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Wait up to $1 seconds for interface $IFACE (hg0) to appear
wait_hg0() {
	local i=0
	while [ "$i" -lt "$1" ]; do
		ip link show hg0 >/dev/null 2>&1 && return 0
		sleep 1
		i=$((i + 1))
	done
	return 1
}

# Read wpa_psk from config file without echoing it anywhere
read_stored_psk() {
	grep -m1 '^wpa_psk=' "${config_file}" 2>/dev/null | cut -d= -f2-
}

# Validate a value is a member of a whitelist (space-separated)
in_list() {
	local val="$1"; shift
	for item in "$@"; do
		[ "$val" = "$item" ] && return 0
	done
	return 1
}

# ---------------------------------------------------------------------------
# POST handler
# ---------------------------------------------------------------------------
if [ "$REQUEST_METHOD" = "POST" ]; then
	for p in $params; do
		eval txw8301_${p}=\$POST_txw8301_${p}
	done

	# --- Validation ---

	# mode
	in_list "$txw8301_mode" sta ap || set_error_flag "Mode must be 'sta' or 'ap'."

	# ssid: 1-32 printable ASCII
	if [ -z "$txw8301_ssid" ]; then
		set_error_flag "SSID cannot be empty."
	elif ! echo "$txw8301_ssid" | grep -Eq '^[[:print:]]{1,32}$'; then
		set_error_flag "SSID must be 1-32 printable characters."
	fi

	# key_mgmt
	in_list "$txw8301_key_mgmt" WPA-PSK NONE || set_error_flag "Key management must be 'WPA-PSK' or 'NONE'."

	# wpa_psk: if non-blank, validate length; if blank, preserve stored value
	if [ -n "$txw8301_wpa_psk" ]; then
		psk_len=$(echo -n "$txw8301_wpa_psk" | wc -c)
		if [ "$psk_len" -lt 8 ] || [ "$psk_len" -gt 63 ]; then
			set_error_flag "PSK must be 8-63 characters when set."
		fi
	else
		# Preserve existing PSK — do not log or expose the value
		txw8301_wpa_psk=$(read_stored_psk)
	fi

	# freq_range: NNNN,NNNN,N[N]
	if ! echo "$txw8301_freq_range" | grep -Eq '^[0-9]{4},[0-9]{4},[0-9]+$'; then
		set_error_flag "Frequency range must be in format NNNN,NNNN,N (e.g. 9080,9240,8)."
	fi

	# chan_list: comma-separated 4-digit frequencies
	if ! echo "$txw8301_chan_list" | grep -Eq '^[0-9]{4}(,[0-9]{4})*$'; then
		set_error_flag "Channel list must be comma-separated 4-digit frequencies (e.g. 9080,9160,9240)."
	fi

	# bss_bw
	in_list "$txw8301_bss_bw" 2 4 8 || set_error_flag "BSS bandwidth must be 2, 4, or 8."

	# tx_mcs: integer 0-255
	if ! echo "$txw8301_tx_mcs" | grep -Eq '^[0-9]+$' || \
	   [ "$txw8301_tx_mcs" -lt 0 ] || [ "$txw8301_tx_mcs" -gt 255 ]; then
		set_error_flag "TX MCS must be an integer between 0 and 255."
	fi

	# dhcpc: 0 or 1 (checkbox sends "true"/"false" via field_switch; normalise)
	[ "$txw8301_dhcpc" = "true" ]  && txw8301_dhcpc=1
	[ "$txw8301_dhcpc" = "false" ] && txw8301_dhcpc=0
	in_list "$txw8301_dhcpc" 0 1 || txw8301_dhcpc=0

	# --- Apply ---
	if [ -z "$error" ]; then
		# Backup current config
		cp -f "${config_file}" "${backup_file}" 2>/dev/null

		# Write new config atomically to a temp file then move
		{
			echo "freq_range=${txw8301_freq_range}"
			echo "bss_bw=${txw8301_bss_bw}"
			echo "tx_mcs=${txw8301_tx_mcs}"
			echo "chan_list=${txw8301_chan_list}"
			echo "key_mgmt=${txw8301_key_mgmt}"
			echo "wpa_psk=${txw8301_wpa_psk}"
			echo "ssid=${txw8301_ssid}"
			echo "mode=${txw8301_mode}"
			echo "dhcpc=${txw8301_dhcpc}"
		} > /tmp/hgicf.conf.new
		chmod 600 /tmp/hgicf.conf.new
		mv /tmp/hgicf.conf.new "${config_file}"

		# Restart service and verify interface comes up
		/etc/init.d/S35txw8301 restart >/dev/null 2>&1

		if wait_hg0 5; then
			redirect_back "success" "TXW8301 config applied."
		else
			# Rollback
			mv -f "${backup_file}" "${config_file}" 2>/dev/null
			/etc/init.d/S35txw8301 restart >/dev/null 2>&1
			set_error_flag "Apply failed: hg0 did not come up. Previous config has been restored."
		fi
	fi

	redirect_to "$SCRIPT_NAME"
fi

# ---------------------------------------------------------------------------
# GET: load current config values
# ---------------------------------------------------------------------------
[ -f "${config_file}" ] && include "${config_file}"

# Normalise dhcpc for field_switch (expects "true"/"false")
[ "$dhcpc" = "1" ] && dhcpc_switch="true" || dhcpc_switch="false"

# Never pre-populate wpa_psk in the form
unset wpa_psk

# Expose config values under txw8301_ prefix for t_value() helper
txw8301_mode="$mode"
txw8301_ssid="$ssid"
txw8301_key_mgmt="$key_mgmt"
txw8301_freq_range="$freq_range"
txw8301_chan_list="$chan_list"
txw8301_bss_bw="$bss_bw"
txw8301_tx_mcs="$tx_mcs"
txw8301_dhcpc="$dhcpc_switch"
%>
<%in p/header.cgi %>

<div class="row g-4">
	<div class="col col-md-6 col-lg-5">

		<% if ip link show hg0 >/dev/null 2>&1; then %>
		<div class="alert alert-success">
			<h5 class="mb-1">Interface hg0 is up</h5>
			<dl class="mb-0 x-small">
				<dt>Address</dt>
				<dd><%= $(ip addr show hg0 2>/dev/null | awk '/inet / {print $2}') %></dd>
			</dl>
		</div>
		<% else %>
		<div class="alert alert-warning">Interface <strong>hg0</strong> is not up.</div>
		<% fi %>

		<form action="<%= $SCRIPT_NAME %>" method="post">
			<h4>Connection</h4>
			<% field_string "txw8301_mode" "Mode" "eval" "sta ap" "sta = client (station); ap = access point (unvalidated on all boards)." %>
			<% field_text "txw8301_ssid" "SSID" "1-32 printable characters." %>
			<% field_string "txw8301_key_mgmt" "Key Management" "eval" "WPA-PSK NONE" %>
			<% field_password "txw8301_wpa_psk" "WPA PSK" "Leave blank to keep the current PSK. Never echoed back." %>

			<h4 class="mt-3">Radio</h4>
			<div class="alert alert-info x-small">
				<strong>freq_range</strong> and <strong>chan_list</strong> must reference
				the same set of HaLow frequencies. Changing one typically requires updating the other.
			</div>
			<% field_text "txw8301_freq_range" "Frequency Range" "Format: START,END,STEP (e.g. 9080,9240,8)." %>
			<% field_text "txw8301_chan_list" "Channel List" "Comma-separated 4-digit frequencies (e.g. 9080,9160,9240)." %>
			<% field_string "txw8301_bss_bw" "BSS Bandwidth (MHz)" "eval" "2 4 8" %>
			<% field_integer "txw8301_tx_mcs" "TX MCS" "$(t_value txw8301_tx_mcs)" "0" "255" "0-255; 255 = auto." %>

			<h4 class="mt-3">Network</h4>
			<% field_switch "txw8301_dhcpc" "Enable DHCP" "eval" "Automatically obtain an IP address via DHCP after interface comes up." %>

			<% button_submit "Save &amp; Apply" %>
		</form>

	</div>

	<div class="col col-md-6 col-lg-7">
		<h4>Interface Status</h4>
		<% ex "ip link show hg0" %>
		<% ex "ip addr show hg0" %>
		<h4 class="mt-3">Current Config</h4>
		<% ex "cat ${config_file}" %>
	</div>
</div>

<script>
function togglePsk() {
	const km = $('#txw8301_key_mgmt').value;
	const wrap = $('#txw8301_wpa_psk_wrap');
	if (km === 'NONE') {
		wrap.classList.add('d-none');
	} else {
		wrap.classList.remove('d-none');
	}
}
$('#txw8301_key_mgmt').addEventListener('change', togglePsk);
togglePsk();

<% if [ "$txw8301_dhcpc" = "true" ]; then %>
$('#txw8301_dhcpc').checked = true;
<% fi %>
</script>

<%in p/footer.cgi %>
